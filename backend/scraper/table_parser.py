"""
Core table parser — works on BeautifulSoup <table> elements or raw 2D arrays.

Handles:
- Raw extraction from HTML tables (with colspan/rowspan)
- Orientation detection and auto-transpose
- Validation / confidence scoring
- Building MeasurementRow objects
- Unit, chart type, and category detection
"""

import re
from bs4 import Tag
from .models import MeasurementRow, SizeChart
from .config import MEASUREMENT_KEYWORDS, NEGATIVE_KEYWORDS, SIZE_LABELS

# --- Size pattern regex (case-insensitive) ---
SIZE_PATTERN = re.compile(
    r'^(XXS|XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL|5XL'
    r'|1X|2X|3X|4X'
    r'|[0-9]{1,2}'
    r'|[0-9]{1,2}\s*[-\u2013]\s*[0-9]{1,2}'
    r'|one\s*size'
    r'|free\s*size'
    r'|OS|F)$',
    re.IGNORECASE
)

# --- Category keywords ---
CATEGORY_KEYWORDS = {
    "tops": ["shirt", "top", "blouse", "tee", "tank", "hoodie", "jacket",
             "sweater", "vest", "polo", "cardigan", "sweatshirt"],
    "bottoms": ["pant", "jean", "trouser", "short", "jogger", "legging",
                "chino", "cargo", "skort"],
    "dresses": ["dress", "skirt", "gown", "romper", "jumpsuit", "maxi", "midi"],
    "shoes": ["shoe", "boot", "sandal", "sneaker", "heel", "loafer", "flat", "oxford"],
}


# ── HTML table extraction ──────────────────────────────────────────

def extract_rows_from_table(table: Tag) -> list[list[str]]:
    """
    Extract a 2D array of strings from a BS4 <table> element.
    Handles colspan and rowspan.
    """
    rows = table.find_all("tr")
    if not rows:
        return []

    # First pass: figure out grid dimensions
    max_cols = 0
    for tr in rows:
        col_count = 0
        for cell in tr.find_all(["th", "td"]):
            col_count += int(cell.get("colspan", 1))
        max_cols = max(max_cols, col_count)

    # Build grid with rowspan/colspan support
    grid = []
    rowspan_tracker = {}  # col_index -> (remaining_rows, value)

    for row_idx, tr in enumerate(rows):
        row_data = [""] * max_cols
        col_idx = 0
        cells = tr.find_all(["th", "td"])
        cell_iter = iter(cells)

        for target_col in range(max_cols):
            # Check if a rowspan from above fills this cell
            if target_col in rowspan_tracker:
                remaining, val = rowspan_tracker[target_col]
                row_data[target_col] = val
                if remaining <= 1:
                    del rowspan_tracker[target_col]
                else:
                    rowspan_tracker[target_col] = (remaining - 1, val)
                continue

            cell = next(cell_iter, None)
            if cell is None:
                break

            text = cell.get_text(strip=True)
            colspan = int(cell.get("colspan", 1))
            rowspan = int(cell.get("rowspan", 1))

            for c in range(colspan):
                idx = target_col + c
                if idx < max_cols:
                    row_data[idx] = text

            if rowspan > 1:
                for c in range(colspan):
                    idx = target_col + c
                    if idx < max_cols:
                        rowspan_tracker[idx] = (rowspan - 1, text)

        # Only add rows that have content
        if any(cell.strip() for cell in row_data):
            grid.append(row_data)

    return grid


def extract_rows_from_html(html_string: str) -> list[list[list[str]]]:
    """
    Find all <table> elements in an HTML string and extract rows from each.
    Returns a list of 2D arrays (one per table).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_string, "lxml")
    tables = soup.find_all("table")
    results = []
    for table in tables:
        rows = extract_rows_from_table(table)
        if len(rows) >= 2:
            results.append(rows)
    return results


# ── Title row skipping ──────────────────────────────────────────────

def _skip_title_rows(rows: list[list[str]]) -> list[list[str]]:
    """Skip title/caption rows at the start of a table."""
    toggle_indicators = {"cmin", "incm", "cm/in", "in/cm", "cmincm", "incmin"}

    for i, row in enumerate(rows):
        non_empty = [c for c in row if c.strip()]
        if non_empty and non_empty[0].strip().lower().replace(" ", "") in toggle_indicators:
            continue
        if len(non_empty) >= 2:
            return rows[i:]
        if len(non_empty) == 1 and not any(c.isdigit() for c in non_empty[0]):
            continue
        break
    return rows


# ── Orientation detection & transpose ───────────────────────────────

def _count_size_matches(cells: list[str]) -> int:
    """Count how many cells match the SIZE_PATTERN."""
    return sum(1 for c in cells if SIZE_PATTERN.match(c.strip()))


def auto_orient(rows: list[list[str]]) -> list[list[str]]:
    """
    Detect if sizes are in the first row (transposed) and transpose if needed.
    Returns the correctly-oriented 2D array.
    """
    if len(rows) < 2:
        return rows

    first_row = rows[0]
    first_col = [row[0] for row in rows if row]

    sizes_in_row = _count_size_matches(first_row)
    sizes_in_col = _count_size_matches(first_col)

    if sizes_in_row > sizes_in_col and sizes_in_row >= 2:
        # Transpose: pad rows to equal length, then zip
        max_len = max(len(r) for r in rows)
        padded = [r + [""] * (max_len - len(r)) for r in rows]
        transposed = [list(col) for col in zip(*padded)]
        return transposed

    return rows


# ── Validation / confidence scoring ─────────────────────────────────

def score_as_size_chart(rows: list[list[str]]) -> float:
    """
    Score how likely a 2D array is a real size chart.
    Returns 0.0 to 1.0.
    """
    rows = _skip_title_rows(rows)
    if len(rows) < 2:
        return 0.0

    headers = [h.lower().strip() for h in rows[0]]
    data_rows = rows[1:]
    score = 0.0

    # Size header present (+0.25)
    size_headers = {"size", "sizes", "uk", "us", "eu", ""}
    if headers and (headers[0] in size_headers or
                    (len(headers) > 1 and headers[1] in size_headers)):
        score += 0.25

    # Measurement keywords in headers (+0.30)
    measurement_hits = sum(
        1 for h in headers
        if any(kw in h for kw in MEASUREMENT_KEYWORDS)
    )
    if measurement_hits > 0:
        score += min(measurement_hits * 0.10, 0.30)

    # First column contains size values (+0.25)
    size_hits = sum(
        1 for row in data_rows
        if row and SIZE_PATTERN.match(row[0].strip())
    )
    if size_hits > 0:
        score += min(size_hits / max(len(data_rows), 1), 1.0) * 0.25

    # At least 3 data rows (+0.10)
    if len(data_rows) >= 3:
        score += 0.10

    # At least 3 columns (+0.10)
    if len(headers) >= 3:
        score += 0.10

    # Penalty for negative keywords
    all_text = " ".join(" ".join(row) for row in rows).lower()
    for neg in NEGATIVE_KEYWORDS:
        if neg in all_text:
            score -= 0.15
            break

    return max(0.0, min(score, 1.0))


# ── Build MeasurementRow objects ────────────────────────────────────

def build_measurement_rows(rows: list[list[str]]) -> tuple[list[str], list[MeasurementRow]]:
    """
    Build MeasurementRow objects from a validated, oriented 2D array.
    Returns (headers, list[MeasurementRow]).
    """
    rows = _skip_title_rows(rows)
    if len(rows) < 2:
        return [], []

    headers = [h.strip() for h in rows[0]]
    # Fix empty first header (common after transpose)
    if headers and not headers[0]:
        headers[0] = "Size"
    data_rows = rows[1:]
    result = []

    for row in data_rows:
        if not row or not row[0].strip():
            continue
        size_label = row[0].strip()
        measurements = {}
        for i, header in enumerate(headers[1:], start=1):
            if i < len(row) and row[i].strip():
                measurements[header] = row[i].strip()
        if measurements:
            result.append(MeasurementRow(size=size_label, measurements=measurements))

    return headers, result


# ── Unit detection ──────────────────────────────────────────────────

def detect_unit(headers: list[str], rows: list[MeasurementRow], page_text: str = "") -> str:
    """
    Detect measurement unit from headers, data values, and page text.
    Returns 'inches', 'cm', 'mixed', or 'unknown'.
    """
    header_text = " ".join(h.lower() for h in headers)

    has_inch = any(kw in header_text for kw in ['(in)', '(inches)', '"', 'inch'])
    has_cm = any(kw in header_text for kw in ['(cm)', 'centimeter', 'centimetre'])

    if has_inch and has_cm:
        return "mixed"
    if has_cm:
        return "cm"
    if has_inch:
        return "inches"

    # Check data values for inch markers
    inch_markers = 0
    total = 0
    for r in rows:
        for val in r.measurements.values():
            total += 1
            if '"' in val or '\u201d' in val:
                inch_markers += 1
    if total > 0 and inch_markers / total > 0.3:
        return "inches"

    # Check page text
    text_lower = page_text.lower()
    if re.search(r'measurements?\s+(are\s+)?in\s+(cm|centimeters?)', text_lower):
        return "cm"
    if re.search(r'measurements?\s+(are\s+)?in\s+(inch|inches)', text_lower):
        return "inches"

    # Heuristic: average numeric value
    nums = []
    for r in rows:
        for val in r.measurements.values():
            for n in re.findall(r'[\d.]+', val):
                try:
                    nums.append(float(n))
                except ValueError:
                    pass
    if nums:
        avg = sum(nums) / len(nums)
        if avg > 50:
            return "cm"
        elif avg < 50:
            return "inches"

    return "unknown"


# ── Chart type detection ────────────────────────────────────────────

def detect_chart_type(headers: list[str], page_text: str = "") -> str:
    """Detect if this is body or garment measurements."""
    combined = " ".join(headers).lower() + " " + page_text[:500].lower()
    if any(kw in combined for kw in ["body", "your"]):
        return "body_measurements"
    if any(kw in combined for kw in ["garment", "flat", "laid flat", "actual"]):
        return "garment_measurements"
    return "unknown"


# ── Category guessing ───────────────────────────────────────────────

def guess_category(product_title: str) -> str:
    """Guess product category from title keywords."""
    title_lower = product_title.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            return category
    return "general"
