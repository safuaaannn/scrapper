"""
Layer 0 — Regex fast-scan. Fetches raw HTML via HTTP and extracts
size charts using store-specific recipes. No browser needed.

Typical time: ~0.3–0.5 sec (vs 5–15 sec with browser).
"""

import json
import logging
import re
from urllib.parse import urlparse

import aiohttp
import pandas as pd

from .config import HEADERS, MEASUREMENT_KEYWORDS, SIZE_LABELS
from .recipes import RECIPES

log = logging.getLogger(__name__)

# Compiled regex for stripping HTML tags from cell content
_TAG_STRIP = re.compile(r"<[^>]+>")

# HTTP fetch timeout (seconds)
_FETCH_TIMEOUT = 8


def find_recipe(url: str) -> dict | None:
    """Look up a recipe for the given URL's domain."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, recipe in RECIPES.items():
        if domain in host:
            return recipe
    return None


async def try_regex_scan(url: str) -> tuple[pd.DataFrame, float]:
    """
    Try to extract a size chart using regex (no browser).

    Returns (DataFrame, confidence) or (empty DataFrame, 0.0).
    Only works for stores that have a recipe in recipes.py.
    """
    recipe = find_recipe(url)
    if not recipe:
        return pd.DataFrame(), 0.0

    store_name = recipe["name"]
    log.info("[regex] Recipe found: %s — fetching HTML...", store_name)

    # Step 1: Fetch raw HTML via HTTP
    html = await _fetch_html(url)
    if not html:
        log.info("[regex] HTTP fetch failed, skipping")
        return pd.DataFrame(), 0.0

    log.info("[regex] Fetched %d chars", len(html))

    # Step 2: Quick check — does this HTML contain measurement keywords?
    html_lower = html.lower()
    has_measurements = any(kw in html_lower for kw in MEASUREMENT_KEYWORDS)
    if not has_measurements:
        log.info("[regex] No measurement keywords in HTML, skipping")
        return pd.DataFrame(), 0.0

    # Step 3: Extract product title
    title = _extract_title(html, url, store_name)
    log.info("[regex] Product: %s", title)

    # Step 4: Apply recipe to extract size chart
    fmt = recipe.get("format", "regex")

    if fmt == "jotly_json":
        df = _extract_jotly_json(html, recipe, title)
    else:
        rows = _apply_recipe(html, recipe)
        if not rows:
            log.info("[regex] Recipe matched no data")
            return pd.DataFrame(), 0.0
        df = _build_dataframe(rows, recipe, title)
    if df.empty:
        return pd.DataFrame(), 0.0

    # Step 6: Compute confidence
    confidence = _compute_confidence(df)
    log.info("[regex] Extracted %d sizes, confidence: %.2f", len(df), confidence)

    return df, confidence


async def _fetch_html(url: str) -> str | None:
    """Fetch raw HTML via aiohttp. Returns None on failure."""
    try:
        timeout = aiohttp.ClientTimeout(total=_FETCH_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=HEADERS, allow_redirects=True) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except Exception:
        return None


def _extract_jotly_json(html: str, recipe: dict, title: str) -> pd.DataFrame:
    """
    Extract size chart from Jotly size chart app JSON embedded in HTML.

    Jotly stores data as: "rows":[[...],[...]],"headers":[...]
    Used by Shopify stores with the Jotly size chart extension.
    """
    # Pattern: "rows":[[row1],[row2],...],"headers":["Size","Chest",...]
    # Also handle reversed order: "headers":[...],...,"rows":[[...]]
    m = re.search(
        r'"rows":\s*(\[\[.*?\]\])\s*,\s*"headers":\s*(\[[^\]]+\])',
        html, re.DOTALL,
    )
    if not m:
        # Try reversed order (headers before rows)
        m = re.search(
            r'"headers":\s*(\[[^\]]+\])\s*,.*?"rows":\s*(\[\[.*?\]\])',
            html, re.DOTALL,
        )
        if m:
            headers_str, rows_str = m.group(1), m.group(2)
        else:
            log.info("[regex] Jotly JSON pattern not found")
            return pd.DataFrame()
    else:
        rows_str, headers_str = m.group(1), m.group(2)

    try:
        headers = json.loads(headers_str)
        rows = json.loads(rows_str)
    except json.JSONDecodeError as e:
        log.info("[regex] Jotly JSON parse error: %s", e)
        return pd.DataFrame()

    if not headers or not rows:
        return pd.DataFrame()

    # Build DataFrame
    fmt = recipe.get("value_format", "plain")
    data = []
    for row in rows:
        d = {}
        for j, h in enumerate(headers):
            val = row[j] if j < len(row) else ""
            d[h] = _parse_value(str(val), fmt)
        data.append(d)

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


def _extract_title(html: str, url: str, brand_name: str) -> str:
    """Extract product title from HTML meta tags or <title>."""
    # Try og:title (cleanest)
    og = re.search(r'property="og:title"\s+content="([^"]*)"', html, re.IGNORECASE)
    if og:
        title = og.group(1).strip()
        # Clean brand name suffix
        title = re.sub(
            rf"\s*[|–\-]\s*{re.escape(brand_name)}.*$", "", title, flags=re.IGNORECASE
        )
        if title:
            return title

    # Try <title> tag
    title_tag = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_tag:
        title = title_tag.group(1).strip()
        title = re.sub(
            rf"\s*[|–\-]\s*{re.escape(brand_name)}.*$", "", title, flags=re.IGNORECASE
        )
        if title:
            return title

    # Fallback: extract from URL
    if "/products/" in url:
        return url.split("/products/")[-1].split("?")[0].replace("-", " ").title()
    return url.rstrip("/").split("/")[-1].replace("-", " ").title()


def _apply_recipe(html: str, recipe: dict) -> list[list[str]]:
    """
    Apply a recipe's regex patterns to extract raw rows of cell values.

    Returns a list of rows, where each row is a list of cleaned cell strings.
    Example: [["US Size","XXS","XS","S"], ["Bust","30/76.2","32/81.3","34/86.4"]]
    """
    # Find the container
    container_match = re.search(recipe["container"], html, re.DOTALL | re.IGNORECASE)
    if not container_match:
        return []

    container_html = container_match.group(0)

    # Find all rows inside the container
    row_matches = re.findall(recipe["row"], container_html, re.DOTALL | re.IGNORECASE)
    if not row_matches:
        return []

    # Extract cells from each row
    rows = []
    for row_html in row_matches:
        cells = re.findall(recipe["cell"], row_html, re.DOTALL | re.IGNORECASE)
        # Strip HTML tags and whitespace from each cell
        cleaned = [_TAG_STRIP.sub("", c).strip() for c in cells]
        if any(cleaned):  # skip empty rows
            rows.append(cleaned)

    return rows


def _parse_value(raw: str, fmt: str) -> str:
    """
    Parse a cell value according to the recipe's value_format.

    plain:         "96"       → "96"
    slash_cm:      "30/76.2"  → "76.2"   (inches/cm → take cm)
    slash_inches:  "76.2/30"  → "76.2"   (cm/inches → take cm)
    """
    raw = raw.strip()
    if not raw:
        return raw

    if fmt == "slash_cm" and "/" in raw:
        parts = raw.split("/")
        return parts[1].strip() if len(parts) == 2 else raw

    if fmt == "slash_inches" and "/" in raw:
        parts = raw.split("/")
        return parts[0].strip() if len(parts) == 2 else raw

    return raw


def _build_dataframe(rows: list[list[str]], recipe: dict, title: str) -> pd.DataFrame:
    """
    Build a DataFrame from extracted rows using the recipe's layout info.

    first_row="headers":  Row 0 is column names, rows 1+ are data.
        Size | Chest | Waist
        S    | 96    | 76
        M    | 100   | 80

    first_row="sizes":  Row 0 is size labels, rows 1+ are measurements (transposed).
        US Size | XXS   | XS    | S
        Bust    | 30/76 | 32/81 | 34/86
        Waist   | 24/61 | 26/66 | 28/71
    """
    fmt = recipe.get("value_format", "plain")
    layout = recipe.get("first_row", "headers")

    if not rows or len(rows) < 2:
        return pd.DataFrame()

    if layout == "headers":
        # Standard table: first row = headers, rest = data rows
        headers = rows[0]
        data = []
        for row in rows[1:]:
            d = {}
            for j, h in enumerate(headers):
                val = row[j] if j < len(row) else ""
                d[h] = _parse_value(val, fmt)
            data.append(d)

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df.insert(0, "Product", title)
        df.insert(1, "Unit", "cm")
        return df

    elif layout == "sizes":
        # Transposed: first row = size labels, other rows = measurements
        size_row = rows[0]
        # First cell is the label (e.g., "US Size"), rest are actual sizes
        size_label = size_row[0]
        sizes = size_row[1:]

        # Build one dict per size
        data = [{"Size": s} for s in sizes]

        for meas_row in rows[1:]:
            if not meas_row:
                continue
            measure_name = meas_row[0]  # e.g., "Bust(inches/cm)"
            # Clean measurement name: "Bust(inches/cm)" → "Bust"
            clean_name = re.sub(r"\s*\(.*?\)\s*$", "", measure_name).strip()
            if not clean_name:
                continue

            values = meas_row[1:]
            for i, size_dict in enumerate(data):
                raw = values[i] if i < len(values) else ""
                size_dict[clean_name] = _parse_value(raw, fmt)

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df.insert(0, "Product", title)
        df.insert(1, "Unit", "cm")
        return df

    return pd.DataFrame()


def _compute_confidence(df: pd.DataFrame) -> float:
    """Score confidence based on DataFrame quality."""
    if df.empty:
        return 0.0

    score = 0.3  # base score — recipe matched

    # Bonus: recognized measurement columns
    cols_lower = {c.lower() for c in df.columns}
    matched_measurements = cols_lower & MEASUREMENT_KEYWORDS
    if matched_measurements:
        score += min(len(matched_measurements) * 0.1, 0.3)

    # Bonus: recognized size labels
    if "Size" in df.columns:
        known = sum(1 for s in df["Size"] if s.upper() in SIZE_LABELS)
        if known >= 2:
            score += 0.2

    # Bonus: numeric values in measurement columns
    numeric_count = 0
    total_count = 0
    for col in df.columns:
        if col in ("Product", "Unit", "Size"):
            continue
        for val in df[col]:
            total_count += 1
            try:
                float(val)
                numeric_count += 1
            except (ValueError, TypeError):
                pass
    if total_count > 0 and numeric_count / total_count >= 0.7:
        score += 0.2

    return min(score, 1.0)
