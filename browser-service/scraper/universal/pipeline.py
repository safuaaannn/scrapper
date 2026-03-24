"""
Universal scraper pipeline — orchestrates discovery, extraction, normalization.

Flow:
  1. Navigate to URL, wait for page load
  2. Extract product title
  3. Run discovery to find and reveal the size chart
  4. Try CM toggle
  5. Extract tables, score them, pick the best
  6. Detect units, convert to CM
  7. Build DataFrame, compute confidence
"""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, get_product_title
from .discovery import discover_size_chart, try_cm_toggle
from .extraction import extract_tables, extract_text_content, pick_best_table, parse_table_data, parse_text_as_table
from .normalization import detect_unit, convert_to_cm, build_dataframe
from .confidence import compute_confidence


async def scrape_universal(product_url: str, browser=None, use_ocr: bool = False) -> tuple:
    """
    Universal size chart scraper — works on any product page.

    Returns:
        (pd.DataFrame, float) — the size chart data and confidence score (0.0 - 1.0)
    """
    own_browser = browser is None
    pw = None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

    # Create page with stealth settings to bypass bot detection
    # Use en-IN locale to avoid geo-popups on Indian stores (Westside, Libas, etc.)
    # Falls back to en-US behavior on non-Indian stores
    ctx = await browser.new_context(
        user_agent=HEADERS["User-Agent"],
        viewport={"width": 1920, "height": 1080},
        locale="en-IN",
    )
    # Init script: remove blocking overlays as soon as they appear (runs before page JS)
    await ctx.add_init_script("""
        Object.defineProperty(navigator, "webdriver", { get: () => false });

        // MutationObserver to auto-remove OneTrust, cookie banners, and region popups
        const _cleanOverlays = () => {
            // OneTrust / CookieBot consent SDKs
            for (const el of document.querySelectorAll(
                '#onetrust-consent-sdk, #CybotCookiebotDialog, [class*="onetrust-pc-dark-filter"]'
            )) el.remove();

            // Region/shipping popup (Westside pattern)
            const rp = document.getElementById('region-popup');
            if (rp) rp.remove();
        };

        // Run on DOM changes
        new MutationObserver(_cleanOverlays).observe(document.documentElement, {
            childList: true, subtree: true
        });

        // Also run periodically for the first few seconds
        let _cleanCount = 0;
        const _cleanInterval = setInterval(() => {
            _cleanOverlays();
            if (++_cleanCount > 20) clearInterval(_cleanInterval);
        }, 250);
    """)
    page = await ctx.new_page()
    try:
        print(f"  [universal] Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)

        # Wait for page to be interactive
        await _wait_for(page, "() => !!document.querySelector('h1') || document.title.length > 5", timeout=15000)

        # Wait for async content to load
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(1500)

        # Dismiss any remaining overlays not caught by init script
        DISMISS_OVERLAYS_JS = """() => {
            // Remove consent SDKs
            for (const el of document.querySelectorAll(
                '#onetrust-consent-sdk, #CybotCookiebotDialog, [id*="cookie-consent"], ' +
                '[class*="onetrust"], [class*="cookiebot"], [class*="cookie-consent"], ' +
                '[class*="dark-filter"]'
            )) el.remove();

            // Remove region/shipping popups by ID
            for (const el of document.querySelectorAll(
                '#region-popup, #overlay, #country-popup, #shipping-popup'
            )) el.remove();

            // Remove shipping popups by heading text
            for (const h1 of document.querySelectorAll('h1, h2, h3')) {
                const text = h1.textContent.trim().toUpperCase();
                if (text.includes('SHIPPING LOCATION') || text.includes('CHOOSE YOUR') ||
                    text.includes('SELECT YOUR COUNTRY')) {
                    let parent = h1.parentElement;
                    for (let i = 0; i < 12; i++) {
                        if (!parent || parent === document.body) break;
                        const style = getComputedStyle(parent);
                        const rect = parent.getBoundingClientRect();
                        if (style.position === 'fixed' || style.position === 'absolute' ||
                            parseInt(style.zIndex) > 100 ||
                            (rect.width >= window.innerWidth * 0.8 && rect.height >= window.innerHeight * 0.8)) {
                            parent.remove();
                            break;
                        }
                        parent = parent.parentElement;
                    }
                }
            }

            // Click cookie accept buttons ONLY (strict exact-match)
            const exactDismiss = new Set([
                'accept all', 'accept all cookies', 'accept cookies', 'reject all',
                'got it', 'i agree', 'continue shopping',
            ]);
            for (const btn of document.querySelectorAll('button, [role="button"]')) {
                const text = btn.textContent.trim().toLowerCase();
                if (text.length > 30 || text.length < 4) continue;
                const rect = btn.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                if (btn.closest('nav, header, .product-form, footer, [class*="region"]')) continue;
                if (exactDismiss.has(text)) { btn.click(); break; }
            }
        }"""
        await page.evaluate(DISMISS_OVERLAYS_JS)
        await page.wait_for_timeout(800)

        # Get product title (use current URL in case of redirect)
        current_url = page.url
        title = await get_product_title(page, current_url)
        print(f"  [universal] Product: {title}")

        # Step 1: Discovery — find and reveal the size chart
        print(f"  [universal] Discovering size chart...")
        discovery_result = await discover_size_chart(page)
        print(f"  [universal] Discovery: {discovery_result}")

        if discovery_result == "not_found":
            print(f"  [universal] No size chart found on page")
            return pd.DataFrame(), 0.0

        # Step 2: Try CM toggle before extracting
        cm_toggled = await try_cm_toggle(page)
        if cm_toggled:
            print(f"  [universal] Clicked CM toggle")
            # Wait for table to update
            await page.wait_for_timeout(500)

        # Step 3: Extract tables
        tables = await extract_tables(page, discovery_result)
        print(f"  [universal] Found {len(tables)} candidate table(s)")

        headers = []
        data_rows = []
        orientation = "unknown"

        if tables:
            # Score and pick the best table
            best = pick_best_table(tables)
            if best:
                headers, data_rows, orientation = parse_table_data(best)
                print(f"  [universal] Best table: {len(data_rows)} rows, {len(headers)} cols, orientation={orientation}")

        # Step 4: If no HTML table found, try text-based extraction
        if not data_rows:
            print(f"  [universal] No HTML table, trying text extraction...")
            text = await extract_text_content(page)
            if text:
                headers, data_rows = parse_text_as_table(text)
                if data_rows:
                    print(f"  [universal] Text extraction: {len(data_rows)} rows")

        # Step 4b: If still no data, look for size chart IMAGES in modals/drawers
        size_chart_image_urls = []
        if not data_rows:
            print(f"  [universal] No text data, checking for size chart images...")
            size_chart_image_urls = await page.evaluate("""() => {
                const urls = [];
                const seen = new Set();

                // Strategy 1: Images with sizeGuide/sizechart in id/class/data attributes
                for (const img of document.querySelectorAll('img')) {
                    const attrs = (img.id || '') + ' ' + (img.className || '');
                    const allDataAttrs = Array.from(img.attributes)
                        .filter(a => a.name.startsWith('data-'))
                        .map(a => a.name + '=' + a.value)
                        .join(' ');
                    const combined = (attrs + ' ' + allDataAttrs).toLowerCase();

                    // Check data-cm, data-inch attributes (Westside pattern)
                    const dataCm = img.getAttribute('data-cm') || '';
                    const dataInch = img.getAttribute('data-inch') || '';

                    if (combined.includes('sizeguide') || combined.includes('size-guide') ||
                        combined.includes('size_guide') || combined.includes('sizechart') ||
                        combined.includes('size-chart') || combined.includes('size_chart') ||
                        dataCm || dataInch) {
                        // Prefer CM version
                        let src = dataCm || img.src || img.getAttribute('data-src') || '';
                        if (src && !seen.has(src)) {
                            if (src.startsWith('//')) src = 'https:' + src;
                            seen.add(src);
                            urls.push(src);
                        }
                    }
                }

                // Strategy 2: Images inside visible modals/drawers with size keywords
                const containers = document.querySelectorAll(
                    '[role="dialog"], [class*="modal"], [class*="drawer"], ' +
                    '[class*="popup"], [class*="sidebar"], dialog[open], ' +
                    'size-guide-drawer, [class*="sizeguide"], [class*="size-guide"]'
                );
                for (const c of containers) {
                    if (c.offsetParent === null && getComputedStyle(c).display === 'none') continue;
                    const text = c.textContent.toLowerCase();
                    if (!text.includes('size')) continue;

                    for (const img of c.querySelectorAll('img')) {
                        const src = img.src || img.getAttribute('data-src') || '';
                        if (src && !seen.has(src) && img.naturalWidth > 100) {
                            if (src.startsWith('//')) { seen.add('https:' + src); urls.push('https:' + src); }
                            else { seen.add(src); urls.push(src); }
                        }
                    }
                }

                // Strategy 3: Any visible image with size/chart/measurement in alt/src
                if (urls.length === 0) {
                    const kw = /size|sizing|measurement|fit.guide|chart/i;
                    for (const img of document.querySelectorAll('img')) {
                        if (img.offsetParent === null) continue;
                        const combined = (img.alt || '') + ' ' + (img.src || '') + ' ' + (img.title || '');
                        if (kw.test(combined)) {
                            let src = img.src || img.getAttribute('data-src') || '';
                            if (src && !seen.has(src)) {
                                if (src.startsWith('//')) src = 'https:' + src;
                                seen.add(src);
                                urls.push(src);
                            }
                        }
                    }
                }

                return urls;
            }""")

            if size_chart_image_urls:
                print(f"  [universal] Found {len(size_chart_image_urls)} size chart image(s)")
                for u in size_chart_image_urls:
                    print(f"    {u[:80]}...")

        # Get page text for unit detection
        page_text = await page.evaluate("() => document.body.innerText")

    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
                await pw.stop()

    if not data_rows:
        # If we found size chart images, try OCR or return them for the caller
        if size_chart_image_urls:
            if use_ocr:
                print(f"  [universal] Running OCR on discovered size chart image(s)...")
                try:
                    from ..ocr import ocr_size_charts
                    charts = ocr_size_charts(size_chart_image_urls, product_url, title)
                    if charts and charts[0].rows:
                        # Convert OCR result to DataFrame for consistency
                        chart = charts[0]
                        rows_for_df = []
                        for mrow in chart.rows:
                            row = {"Size": mrow.size}
                            row.update(mrow.measurements)
                            rows_for_df.append(row)
                        df = pd.DataFrame(rows_for_df)
                        df.insert(0, "Product", title)
                        df.insert(1, "Unit", chart.unit)
                        print(f"  [universal] OCR extracted {len(chart.rows)} sizes")
                        return df, chart.confidence
                except Exception as e:
                    print(f"  [universal] OCR failed: {e}")

            # Return image URLs as metadata even without OCR
            # Store them so the caller can handle them
            print(f"  [universal] No table data, but found size chart image(s)")
            return pd.DataFrame({"_image_urls": [",".join(size_chart_image_urls)]}), 0.0

        print(f"  [universal] No size chart data extracted")
        return pd.DataFrame(), 0.0

    # Step 5: Detect units and convert
    # Always run detection on actual data — CM toggle may not have worked
    unit = detect_unit(page_text, headers, data_rows)
    print(f"  [universal] Detected unit: {unit}")

    data_rows = convert_to_cm(data_rows, headers, unit)

    # Step 6: Build DataFrame
    df = build_dataframe(headers, data_rows, title)

    # Step 7: Compute confidence
    confidence = compute_confidence(headers, data_rows, unit, discovery_result)
    print(f"  [universal] Confidence: {confidence}")

    return df, confidence
