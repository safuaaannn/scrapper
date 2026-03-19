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


async def scrape_universal(product_url: str, browser=None) -> tuple:
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
    ctx = await browser.new_context(
        user_agent=HEADERS["User-Agent"],
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    await ctx.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => false });')
    page = await ctx.new_page()
    try:
        print(f"  [universal] Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)

        # Wait for page to be interactive
        await _wait_for(page, "() => !!document.querySelector('h1') || document.title.length > 5", timeout=8000)

        # Dismiss common overlays (cookie banners, country selectors, popups)
        await page.evaluate("""() => {
            // Hide overlay/modal blockers
            const blockers = document.querySelectorAll(
                '#overlay, [id*="country_selector"], [class*="cookie-banner"], ' +
                '[class*="newsletter-popup"], [class*="popup-overlay"], ' +
                '[class*="geo-modal"], [class*="location-modal"]'
            );
            for (const b of blockers) b.style.display = 'none';

            // Try clicking common dismiss buttons — only <button> elements to avoid navigation
            const dismissTexts = ['accept', 'continue', 'close', 'dismiss', 'got it', 'ok', '×', 'x'];
            for (const btn of document.querySelectorAll('button, span, [role="button"]')) {
                const text = btn.textContent.trim().toLowerCase();
                const rect = btn.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && dismissTexts.includes(text)) {
                    // Skip if it's inside a nav or could trigger navigation
                    if (btn.closest('nav, header')) continue;
                    btn.click();
                    break;
                }
            }
        }""")
        await page.wait_for_timeout(500)

        # Wait for any redirect to settle
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

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
