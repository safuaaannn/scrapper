"""
Shopify API fallback — try to extract size chart from product JSON endpoint.

Many Shopify stores expose /products/<handle>.json which may contain
size chart data embedded in the product body HTML.
"""

import re
import pandas as pd
from .helpers import launch_browser, create_stealth_context


async def try_shopify_api(product_url: str, browser=None) -> tuple:
    """
    Try to fetch size chart from Shopify's product JSON API.
    Returns (pd.DataFrame, float confidence) or (empty DataFrame, 0.0).
    """
    if "/products/" not in product_url:
        return pd.DataFrame(), 0.0

    json_url = product_url.split("?")[0]
    if not json_url.endswith(".json"):
        json_url += ".json"

    own_browser = browser is None
    pw = None
    if own_browser:
        pw, browser = await launch_browser()

    ctx = await create_stealth_context(browser)
    page = await ctx.new_page()
    try:
        response = await page.goto(json_url, wait_until="domcontentloaded", timeout=15000)
        if not response or response.status != 200:
            return pd.DataFrame(), 0.0

        text = await page.evaluate("() => document.body.innerText")
        if not text:
            return pd.DataFrame(), 0.0

        import json
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return pd.DataFrame(), 0.0

        product = data.get("product", {})
        body_html = product.get("body_html", "")
        title = product.get("title", "")

        if not body_html:
            return pd.DataFrame(), 0.0

        # Parse tables from body_html
        df = _parse_html_tables(body_html, title)
        if not df.empty:
            return df, 0.4  # Low confidence — embedded tables may not be size charts

        return pd.DataFrame(), 0.0

    except Exception:
        return pd.DataFrame(), 0.0
    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
                await pw.stop()


def _parse_html_tables(html: str, title: str) -> pd.DataFrame:
    """Parse HTML tables from product body_html."""
    # Simple regex-based table parser (no BS4 dependency)
    table_pattern = re.compile(r'<table[^>]*>(.*?)</table>', re.DOTALL | re.IGNORECASE)
    row_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    cell_pattern = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL | re.IGNORECASE)
    tag_strip = re.compile(r'<[^>]+>')

    tables = table_pattern.findall(html)
    if not tables:
        return pd.DataFrame()

    best_df = pd.DataFrame()
    for table_html in tables:
        rows_html = row_pattern.findall(table_html)
        if len(rows_html) < 2:
            continue

        parsed_rows = []
        for row_html in rows_html:
            cells = cell_pattern.findall(row_html)
            cleaned = [tag_strip.sub("", c).strip() for c in cells]
            parsed_rows.append(cleaned)

        if not parsed_rows:
            continue

        # Check if this looks like a size chart
        all_text = " ".join(" ".join(row) for row in parsed_rows).lower()
        if "size" in all_text and any(kw in all_text for kw in
                ("chest", "waist", "hip", "bust", "shoulder", "length", "inseam")):
            headers = parsed_rows[0]
            data_rows = []
            for row in parsed_rows[1:]:
                if not any(c.strip() for c in row):
                    continue
                d = {}
                for j, h in enumerate(headers):
                    if j < len(row):
                        d[h] = row[j]
                data_rows.append(d)

            if data_rows:
                df = pd.DataFrame(data_rows)
                df.insert(0, "Product", title)
                df.insert(1, "Unit", "cm")
                if len(df) > len(best_df):
                    best_df = df

    return best_df
