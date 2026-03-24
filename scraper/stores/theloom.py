"""The Loom store scraper."""

import re
import pandas as pd
from ..config import INCH_TO_CM
from ..helpers import _wait_for, _click_and_wait, launch_browser, create_stealth_context


async def scrape_theloom(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    pw = None
    if own_browser:
        pw, browser = await launch_browser()

    ctx = await create_stealth_context(browser, locale="en-IN")
    page = await ctx.new_page()
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await _wait_for(page, """() => {
            for (const el of document.querySelectorAll('b, span')) {
                if (el.textContent.trim() === 'Size Chart') return true;
            }
            return false;
        }""", timeout=10000)

        title = await page.evaluate("""() => {
            let t = document.title || '';
            t = t.replace(/^Buy\\s+/i, '').replace(/\\s*[|].*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.rstrip("/").split("/")[-1].replace("-", " ").title()

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('b, span, a, button, div')) {
                const t = el.textContent.trim();
                if ((t === 'Size Chart' || t === 'SIZE CHART') && el.children.length <= 1) {
                    el.click(); return true;
                }
            }
            return false;
        }""", "() => document.querySelectorAll('table').length > 0", timeout=6000)
        if not clicked:
            return pd.DataFrame()

        await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('button, span, div')) {
                const t = el.textContent.trim();
                if ((t === 'Cm' || t === 'CM' || t === 'cm') && el.children.length === 0) {
                    el.click(); return true;
                }
            }
            return false;
        }""", None)

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

        page_text = await page.evaluate("() => document.body.innerText")
    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
                await pw.stop()

    dupatta_info = {}
    if page_text:
        for line in page_text.split("\n"):
            if "dupatta" in line.lower() and ("length" in line.lower() or "width" in line.lower()):
                length_match = re.search(r'Length[-:\s]*([\d.]+)\s*(mtr|m|cm)', line, re.IGNORECASE)
                width_match = re.search(r'Width[-:\s]*([\d.]+)\s*["\u201d]?', line, re.IGNORECASE)
                if length_match:
                    val = float(length_match.group(1))
                    unit = length_match.group(2).lower()
                    if unit in ("mtr", "m"):
                        dupatta_info["Dupatta Length"] = round(val * 100, 1)
                    else:
                        dupatta_info["Dupatta Length"] = val
                if width_match:
                    val = float(width_match.group(1))
                    dupatta_info["Dupatta Width"] = round(val * INCH_TO_CM, 1)
                break

    if not table_data or len(table_data) < 2:
        return pd.DataFrame()

    all_rows = []
    current_section = ""
    sizes = []

    for table_row in table_data:
        non_empty = [c for c in table_row if c.strip()]
        if not non_empty:
            continue
        if len(non_empty) == 1 and not table_row[0].replace(" ", "").isdigit():
            first = table_row[0].strip()
            if first and not any(c.isdigit() for c in first):
                current_section = first
                sizes = []
                continue
        if not table_row[0].strip() and len(non_empty) >= 2:
            candidate_sizes = [c.strip() for c in table_row[1:] if c.strip()]
            if candidate_sizes:
                sizes = candidate_sizes
                continue
        measure_name = table_row[0].strip()
        if measure_name and sizes:
            values = table_row[1:]
            for i, size in enumerate(sizes):
                if i < len(values) and values[i].strip():
                    row = None
                    for r in all_rows:
                        if r.get("Section") == current_section and r["Size"] == size:
                            row = r
                            break
                    if row is None:
                        row = {"Section": current_section, "Size": size}
                        all_rows.append(row)
                    row[measure_name] = values[i].strip()

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    if df["Section"].nunique() <= 1:
        df = df.drop(columns=["Section"])
    if dupatta_info:
        for col, val in dupatta_info.items():
            df[col] = val

    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
