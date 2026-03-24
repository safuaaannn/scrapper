"""
Normalization module — detect units, convert to CM, standardize columns.
"""

import re
import pandas as pd
from ..config import INCH_TO_CM, MEASUREMENT_KEYWORDS
from ..helpers import _inch_range_to_cm


def detect_unit(page_text: str, headers: list, data_rows: list) -> str:
    """
    Detect whether measurement values are in inches or cm.
    Returns 'cm', 'inches', or 'unknown'.
    """
    text_lower = page_text.lower() if page_text else ""

    # Strategy 1: Explicit text on page
    cm_patterns = [
        r'measurements?\s+(?:are\s+)?in\s+(?:cm|centimeters?|centimetres?)',
        r'all\s+(?:sizes?\s+)?in\s+cm',
        r'unit[:\s]+cm',
    ]
    inch_patterns = [
        r'measurements?\s+(?:are\s+)?in\s+(?:inch|inches|in\b)',
        r'all\s+(?:sizes?\s+)?in\s+inches?',
        r'unit[:\s]+inch',
    ]
    for pat in cm_patterns:
        if re.search(pat, text_lower):
            return "cm"
    for pat in inch_patterns:
        if re.search(pat, text_lower):
            return "inches"

    # Strategy 2: Header annotations
    header_text = " ".join(h.lower() for h in headers)
    if "(cm)" in header_text or "- cm" in header_text:
        return "cm"
    if "(in)" in header_text or "(inches)" in header_text or '(")' in header_text:
        return "inches"

    # Strategy 2b: Check actual data values for inch markers (", '', in)
    inch_marker_count = 0
    total_values = 0
    for row in data_rows:
        for key, val in row.items():
            if key.lower() in ("size", "product", "unit", "section"):
                continue
            val_str = str(val)
            total_values += 1
            if '"' in val_str or '\u201d' in val_str or val_str.endswith('"'):
                inch_marker_count += 1
    if total_values > 0 and inch_marker_count / total_values > 0.3:
        return "inches"

    # Strategy 3: Value range heuristics
    # Collect all numeric values from measurement columns
    numeric_values = []
    measurement_cols = set()
    for h in headers:
        if h.lower().strip() in MEASUREMENT_KEYWORDS or any(kw in h.lower() for kw in MEASUREMENT_KEYWORDS):
            measurement_cols.add(h)

    for row in data_rows:
        for col in measurement_cols:
            val = row.get(col, "")
            # Extract numeric part
            nums = re.findall(r'[\d.]+', str(val))
            for n in nums:
                try:
                    numeric_values.append(float(n))
                except ValueError:
                    pass

    if not numeric_values and data_rows:
        # Try all non-size columns
        for row in data_rows:
            for key, val in row.items():
                if key.lower() in ("size", "product", "unit", "section"):
                    continue
                nums = re.findall(r'[\d.]+', str(val))
                for n in nums:
                    try:
                        numeric_values.append(float(n))
                    except ValueError:
                        pass

    if numeric_values:
        avg = sum(numeric_values) / len(numeric_values)
        # CM values are typically 30-150, inch values are 10-60
        if avg > 50:
            return "cm"
        elif avg < 50:
            return "inches"

    return "unknown"


def convert_to_cm(data_rows: list, headers: list, unit: str) -> list:
    """Convert all measurement values to CM if they are in inches."""
    if unit == "cm":
        return data_rows

    skip_cols = {"size", "product", "unit", "section"}
    converted = []

    for row in data_rows:
        new_row = {}
        for key, val in row.items():
            if key.lower() in skip_cols:
                new_row[key] = val
                continue

            if unit == "inches":
                new_row[key] = _inch_range_to_cm(str(val))
            else:
                # Unknown unit — try heuristic on this specific value
                nums = re.findall(r'[\d.]+', str(val))
                if nums:
                    try:
                        num_val = float(nums[0])
                        if num_val < 50:
                            # Likely inches
                            new_row[key] = _inch_range_to_cm(str(val))
                        else:
                            new_row[key] = val
                    except ValueError:
                        new_row[key] = val
                else:
                    new_row[key] = val
        converted.append(new_row)

    return converted


# Common column name aliases to standardize
COLUMN_ALIASES = {
    "hips": "Hip",
    "across shoulder": "Shoulder",
    "across shoulders": "Shoulder",
    "body length": "Length",
    "body width": "Width",
    "front length": "Front Length",
    "back length": "Back Length",
    "arm length": "Sleeve",
    "arm hole": "Armhole",
}


def standardize_columns(headers: list) -> list:
    """Standardize column names."""
    result = []
    for h in headers:
        h_stripped = h.strip()
        h_lower = h_stripped.lower()
        if h_lower in COLUMN_ALIASES:
            result.append(COLUMN_ALIASES[h_lower])
        else:
            # Capitalize first letter of each word
            result.append(h_stripped.title() if h_stripped else h_stripped)
    return result


def build_dataframe(headers: list, data_rows: list, title: str) -> pd.DataFrame:
    """Build the final DataFrame with Product and Unit columns."""
    if not data_rows:
        return pd.DataFrame()

    # Standardize column names
    std_headers = standardize_columns(headers)
    renamed_rows = []
    for row in data_rows:
        new_row = {}
        for old_h, new_h in zip(headers, std_headers):
            if old_h in row:
                new_row[new_h] = row[old_h]
        # Copy any extra keys not in headers
        for key in row:
            if key not in headers:
                new_row[key] = row[key]
        renamed_rows.append(new_row)

    df = pd.DataFrame(renamed_rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df
