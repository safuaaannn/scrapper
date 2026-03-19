"""Good American store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait


async def scrape_goodamerican(product_url: str, browser=None) -> pd.DataFrame:
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
            t = t.replace(/\\s*[|–-]\\s*Good American.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('button')) {
                if (el.textContent.trim() === 'Size Guide') { el.click(); return true; }
            }
            return false;
        }""", "() => document.querySelectorAll('table').length > 0", timeout=8000)
        if not clicked:
            return pd.DataFrame()

        await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('button, span, div')) {
                const t = el.textContent.trim();
                if ((t === 'CM' || t === 'Cm' || t === 'cm') && el.children.length === 0) {
                    el.click(); return true;
                }
            }
            return false;
        }""", None)

        table_data = await page.evaluate("""() => {
            for (const table of document.querySelectorAll('table')) {
                if (table.offsetParent === null) continue;
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

    headers = table_data[0]
    rows = []
    for row_data in table_data[1:]:
        if not any(cell.strip() for cell in row_data):
            continue
        row = {}
        for j, header in enumerate(headers):
            if j < len(row_data):
                row[header] = row_data[j]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
