"""Shared helper functions used by both store-specific and universal scrapers."""

import re
from .config import HEADERS, INCH_TO_CM


async def create_stealth_context(browser, locale="en-US"):
    """Create a browser context with anti-bot stealth settings."""
    ctx = await browser.new_context(
        user_agent=HEADERS["User-Agent"],
        viewport={"width": 1920, "height": 1080},
        locale=locale,
    )
    await ctx.add_init_script("""
        Object.defineProperty(navigator, "webdriver", { get: () => false });
    """)
    return ctx


async def _wait_for(page, js_condition: str, timeout: int = 8000, interval: int = 400):
    """Poll a JS condition every `interval` ms, up to `timeout` ms. Returns result."""
    elapsed = 0
    while elapsed < timeout:
        result = await page.evaluate(js_condition)
        if result:
            return result
        await page.wait_for_timeout(interval)
        elapsed += interval
    return None


async def _click_and_wait(page, click_js: str, wait_js: str, timeout: int = 6000):
    """Click an element then wait for a condition. Returns True on success."""
    clicked = await page.evaluate(click_js)
    if not clicked:
        return False
    if wait_js:
        await _wait_for(page, wait_js, timeout=timeout, interval=400)
    else:
        await page.wait_for_timeout(500)
    return True


def _inch_range_to_cm(val: str):
    """
    Convert inch range like '31 – 33"' or '33 1/2 – 35 1/2"' to cm.
    Returns averaged cm value, or original string if not parseable.
    """
    # Replace Unicode fraction characters with decimal equivalents
    UNICODE_FRACTIONS = {
        '½': '.5', '¼': '.25', '¾': '.75',
        '⅓': '.333', '⅔': '.667',
        '⅛': '.125', '⅜': '.375', '⅝': '.625', '⅞': '.875',
        '⅙': '.167', '⅚': '.833',
    }
    for uf, dec in UNICODE_FRACTIONS.items():
        val = val.replace(uf, dec)

    val = val.replace('\xa0', ' ').replace('\u201d', '').replace('"', '').strip()

    def parse_fraction(s):
        s = s.strip()
        # Handle "17.25" or "17.5" (already decimal after Unicode replacement)
        # Handle "33 1/2" style fractions
        match = re.match(r'(\d+)\s+(\d+)/(\d+)', s)
        if match:
            return int(match.group(1)) + int(match.group(2)) / int(match.group(3))
        try:
            return float(s)
        except ValueError:
            return None

    # Try range: "31 – 33" or "33 1/2 – 35 1/2"
    parts = re.split(r'\s*[–\-]\s*', val)
    if len(parts) == 2:
        low = parse_fraction(parts[0])
        high = parse_fraction(parts[1])
        if low is not None and high is not None:
            avg = (low + high) / 2
            return round(avg * INCH_TO_CM, 1)

    # Try single number
    num = parse_fraction(val)
    if num is not None:
        return round(num * INCH_TO_CM, 1)

    return val


async def get_product_title(page, url: str, brand_name: str = "") -> str:
    """Extract product title from page, with brand name cleanup."""
    title = await page.evaluate("""() => {
        // Skip known popup/overlay headings
        const skipPatterns = /shipping location|choose your|select your country|select region|verified|facebook/i;

        // Try specific product title selectors first
        for (const sel of ['[data-testid="product-title"]', '.product__title',
                           '[class*="product-title"]', '[class*="ProductTitle"]']) {
            const el = document.querySelector(sel);
            if (el) return el.textContent.trim().replace(/\\s+/g, ' ');
        }

        // Fall back to h1, but skip popup headings
        for (const h1 of document.querySelectorAll('h1')) {
            const text = h1.textContent.trim().replace(/\\s+/g, ' ');
            if (text.length > 2 && !skipPatterns.test(text)) {
                return text;
            }
        }

        // Last resort: page title
        let t = document.title || '';
        t = t.trim().replace(/\\s+/g, ' ');
        // Clean common title suffixes
        t = t.replace(/\\s*[|–\\-]\\s*(Facebook|Instagram|Twitter).*$/i, '');
        return t;
    }""")

    if title and brand_name:
        # Clean brand name from title
        title = re.sub(rf'\s*[|–\-]\s*{re.escape(brand_name)}.*$', '', title, flags=re.IGNORECASE)
        title = re.sub(r'^Buy\s+', '', title, flags=re.IGNORECASE)

    if not title:
        # Fallback: extract from URL
        if "/products/" in url:
            title = url.split("/products/")[-1].split("?")[0].replace("-", " ").title()
        else:
            title = url.rstrip("/").split("/")[-1].replace("-", " ").title()

    title = title.strip()

    # De-duplicate if the title is repeated (e.g., "Product Name Product Name")
    half = len(title) // 2
    if half > 5 and title[:half].strip() == title[half:].strip():
        title = title[:half].strip()

    return title
