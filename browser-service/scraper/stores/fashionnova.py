"""Fashion Nova store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait, create_stealth_context


async def scrape_fashionnova(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    pw = None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

    ctx = await create_stealth_context(browser)
    page = await ctx.new_page()
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        await _wait_for(page, "() => !!document.querySelector('h1')", timeout=10000)

        title = await page.evaluate("""() => {
            const el = document.querySelector('h1, [data-testid="product-title"]');
            return el ? el.textContent.trim() : '';
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if (t === 'View Size Guide' && el.children.length <= 1) { el.click(); return true; }
            }
            return false;
        }""", "() => document.body.innerText.includes('Measurements')", timeout=5000)
        if not clicked:
            return pd.DataFrame()

        await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                if (el.textContent.trim() === 'cm' && el.children.length === 0) { el.click(); return true; }
            }
            return false;
        }""", None)

        text = await page.evaluate("() => document.body.innerText")
    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
                await pw.stop()

    return _parse_fashionnova_text(text, product_url, title)


def _parse_fashionnova_text(text, product_url, title):
    lines = text.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Measurements":
            start_idx = i
            break
    if start_idx is None:
        return pd.DataFrame()

    header_idx = None
    headers = []
    for i in range(start_idx, min(start_idx + 10, len(lines))):
        line = lines[i].strip()
        if "Size" in line and "\t" in line:
            headers = [h.strip() for h in line.split("\t") if h.strip()]
            header_idx = i
            break
    if not headers:
        return pd.DataFrame()

    size_values = {"XS", "S", "M", "L", "XL", "1X", "2X", "3X", "XXS", "XXL", "XXXL"}
    rows = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if not parts:
            continue
        if parts[0].upper() in size_values:
            row = {}
            for j, header in enumerate(headers):
                if j < len(parts):
                    row[header] = parts[j]
            rows.append(row)
        else:
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
