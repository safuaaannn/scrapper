"""Rare Rabbit store scraper."""

import pandas as pd
from ..config import HEADERS
from ..helpers import _wait_for, _click_and_wait, create_stealth_context


async def scrape_rarerabbit(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    pw = None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

    ctx = await create_stealth_context(browser, locale="en-IN")
    page = await ctx.new_page()
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        await _wait_for(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim().toUpperCase();
                if (t === 'SIZE GUIDE' || t === 'SIZE CHART') return true;
            }
            return false;
        }""", timeout=10000)

        title = await page.evaluate("""() => {
            const el = document.querySelector('h1, .product__title, [class*="product-title"]');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Rare Rabbit.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim().toUpperCase();
                if ((t === 'SIZE GUIDE' || t === 'SIZE CHART') && el.children.length <= 1) {
                    el.click(); return true;
                }
            }
            return false;
        }""", "() => document.querySelectorAll('table').length > 0", timeout=6000)
        if not clicked:
            return pd.DataFrame()

        table_data = await page.evaluate("""() => {
            let table = document.querySelector('table[class*="ks-table"], .kiwi-sizing table, table.ks-table');
            if (!table) {
                for (const t of document.querySelectorAll('table')) {
                    if (t.offsetParent !== null && t.rows.length > 1) { table = t; break; }
                }
            }
            if (!table) return null;
            const rows = [];
            for (const tr of table.rows) {
                const cells = [];
                for (const td of tr.cells) cells.push(td.textContent.trim());
                rows.push(cells);
            }
            return rows;
        }""")
    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
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
