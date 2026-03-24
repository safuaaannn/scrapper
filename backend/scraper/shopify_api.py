"""
Shopify API fallback — extract size chart from product JSON endpoint.

Uses requests (no browser needed) to fetch /products/<handle>.json
and parse tables from the body_html field.
"""

import re
import pandas as pd
from .static_fetcher import fetch_product_json
from .table_parser import extract_rows_from_html, auto_orient, score_as_size_chart, build_measurement_rows


async def try_shopify_api(product_url: str, browser=None) -> tuple:
    """
    Try to fetch size chart from Shopify's product JSON API.
    Returns (pd.DataFrame, float confidence) or (empty DataFrame, 0.0).

    Note: browser parameter kept for backward compat but is NOT used.
    This now uses requests instead of Playwright.
    """
    if "/products/" not in product_url:
        return pd.DataFrame(), 0.0

    product = fetch_product_json(product_url)
    if not product:
        return pd.DataFrame(), 0.0

    body_html = product.get("body_html", "")
    title = product.get("title", "")

    if not body_html:
        return pd.DataFrame(), 0.0

    # Parse tables from body_html using the new table parser
    tables_2d = extract_rows_from_html(body_html)
    if not tables_2d:
        # Fallback to regex parser for malformed HTML
        df = _parse_html_tables_regex(body_html, title)
        if not df.empty:
            return df, 0.4
        return pd.DataFrame(), 0.0

    best_df = pd.DataFrame()
    best_confidence = 0.0

    for rows_2d in tables_2d:
        rows_2d = auto_orient(rows_2d)
        confidence = score_as_size_chart(rows_2d)

        if confidence < 0.3:
            continue

        headers, mrows = build_measurement_rows(rows_2d)
        if not mrows:
            continue

        # Convert to DataFrame for backward compat
        records = []
        for r in mrows:
            row = {"Size": r.size}
            row.update(r.measurements)
            records.append(row)

        df = pd.DataFrame(records)
        df.insert(0, "Product", title)
        df.insert(1, "Unit", "cm")

        if confidence > best_confidence:
            best_df = df
            best_confidence = confidence

    if not best_df.empty:
        return best_df, best_confidence

    return pd.DataFrame(), 0.0


def _parse_html_tables_regex(html: str, title: str) -> pd.DataFrame:
    """Fallback regex-based table parser for malformed HTML."""
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
