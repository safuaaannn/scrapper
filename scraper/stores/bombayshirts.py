"""Bombay Shirts store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait


async def scrape_bombayshirts(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

    page = await browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await _wait_for(page, "() => !!document.querySelector('h1') || document.title.length > 10", timeout=6000)

        title = await page.evaluate("""() => {
            let t = document.title || '';
            t = t.replace(/\\s*[–—|\\-]\\s*Bombay Shirt.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if ((t === 'Size Guide' || t === 'SIZE GUIDE' || t === 'Size guide') && el.children.length <= 2) {
                    el.click(); return true;
                }
            }
            return false;
        }""", "() => document.querySelectorAll('table').length > 2", timeout=6000)
        if not clicked:
            return pd.DataFrame()

        all_tables = await page.evaluate("""() => {
            const results = [];
            for (const table of document.querySelectorAll('table')) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) results.push(rows);
            }
            return results;
        }""")
    finally:
        await page.close()
        if own_browser:
            await browser.close()
            await pw.stop()

    if not all_tables:
        return pd.DataFrame()

    candidates = []
    for table in all_tables:
        headers = table[0]
        if not headers or "Size" not in headers[0]:
            continue
        is_cm = False
        for row in table[1:]:
            for val in row[1:]:
                try:
                    if float(val) > 50:
                        is_cm = True
                        break
                except ValueError:
                    continue
            if is_cm:
                break
        if is_cm:
            candidates.append(table)

    best_table = None
    if candidates:
        def table_score(t):
            num_cols = len(t[0])
            total = 0
            for row in t[1:]:
                for val in row[1:]:
                    try:
                        total += float(val)
                    except ValueError:
                        pass
            return (num_cols, total)
        best_table = max(candidates, key=table_score)

    if not best_table or len(best_table) < 2:
        return pd.DataFrame()

    headers = best_table[0]
    rows = []
    for row_data in best_table[1:]:
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
