"""Libas store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait


async def scrape_libas(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

    page = await browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await _wait_for(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                if (el.textContent.trim() === 'View Size Chart') return true;
            }
            return false;
        }""", timeout=10000)

        title = await page.evaluate("""() => {
            const el = document.querySelector('h1, .product__title, [class*="product-title"]');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Libas.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if ((t === 'View Size Chart' || t === 'VIEW SIZE CHART') && el.children.length <= 1) {
                    el.click(); return true;
                }
            }
            return false;
        }""", "() => document.body.innerText.includes('Body Measurement')", timeout=6000)
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
        if own_browser:
            await browser.close()
            await pw.stop()

    return _parse_libas_text(text, product_url, title)


def _parse_libas_text(text, product_url, title):
    lines = text.split("\n")
    start_idx = None
    for i, line in enumerate(lines):
        if "Body Measurement" in line:
            start_idx = i
            break
    if start_idx is None:
        return pd.DataFrame()

    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "indicative" in lines[i].lower() or "these measurement" in lines[i].lower():
            end_idx = i
            break

    all_rows = []
    current_section = ""
    sizes = []

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if not line:
            continue
        if line in ("TOP", "BOTTOM", "DUPATTA", "KURTA", "PALAZZO",
                     "PANT", "SKIRT", "DRESS", "JACKET"):
            current_section = line
            sizes = []
            continue
        if line in ("Body Measurement", "inch", "cm"):
            continue
        if "\t" not in line:
            continue

        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 2:
            continue

        label = parts[0]
        values = parts[1:]

        if label.lower() in ("size", "bottom size"):
            sizes = values
            continue

        if sizes:
            for j, size in enumerate(sizes):
                if j < len(values):
                    row = None
                    for r in all_rows:
                        if r["Section"] == current_section and r["Size"] == size:
                            row = r
                            break
                    if row is None:
                        row = {"Section": current_section, "Size": size}
                        all_rows.append(row)
                    row[label] = values[j]

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
