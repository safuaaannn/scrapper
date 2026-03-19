"""Outdoor Voices store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait, _inch_range_to_cm


async def scrape_outdoorvoices(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

    page = await browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await _wait_for(page, "() => !!document.querySelector('h1')", timeout=6000)

        title = await page.evaluate("""() => {
            const el = document.querySelector('h1');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Outdoor Voices.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('button, a, span')) {
                if (el.textContent.trim() === 'Size Guide') { el.click(); return true; }
            }
            return false;
        }""", "() => document.querySelectorAll('table').length > 0", timeout=6000)
        if not clicked:
            return pd.DataFrame()

        table_data = await page.evaluate("""() => {
            for (const table of document.querySelectorAll('table')) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) return rows;
            }
            return null;
        }""")
    finally:
        await page.close()
        if own_browser:
            await browser.close()
            await pw.stop()

    if not table_data or len(table_data) < 2:
        return pd.DataFrame()

    sizes = table_data[0][1:]
    rows = []
    for i, size in enumerate(sizes):
        if not size.strip():
            continue
        row = {"Size": size}
        for data_row in table_data[1:]:
            if len(data_row) < 2:
                continue
            measure_name = data_row[0]
            if not measure_name.strip():
                continue
            if i + 1 < len(data_row):
                val = data_row[i + 1]
                row[measure_name] = _inch_range_to_cm(val)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
