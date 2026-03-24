"""
Confidence scoring for scrape results.
"""

from ..config import MEASUREMENT_KEYWORDS, SIZE_LABELS


def compute_confidence(headers: list, data_rows: list, unit_source: str,
                       discovery_method: str) -> float:
    """
    Compute a confidence score (0.0 - 1.0) for the scrape result.

    Factors:
    - Has Size column
    - Has measurement keyword columns
    - Has numeric data
    - Unit was explicitly detected (not heuristic)
    - Discovery method reliability
    """
    if not headers or not data_rows:
        return 0.0

    score = 0.0
    max_score = 0.0

    # 1. Has Size column (20 points)
    max_score += 20
    has_size = any("size" in h.lower() for h in headers)
    if has_size:
        score += 20

    # 2. Has measurement keywords in headers (30 points max)
    max_score += 30
    measurement_hits = 0
    for h in headers:
        h_lower = h.lower().strip()
        if any(kw in h_lower for kw in MEASUREMENT_KEYWORDS):
            measurement_hits += 1
    score += min(measurement_hits * 10, 30)

    # 3. Data rows have known size labels (15 points)
    max_score += 15
    size_hits = 0
    for row in data_rows:
        size_val = row.get("Size", row.get("size", ""))
        if str(size_val).strip().upper() in SIZE_LABELS:
            size_hits += 1
    if data_rows:
        score += (size_hits / len(data_rows)) * 15

    # 4. Numeric data present (15 points)
    max_score += 15
    numeric_count = 0
    total_values = 0
    for row in data_rows:
        for key, val in row.items():
            if key.lower() in ("size", "product", "unit", "section"):
                continue
            total_values += 1
            try:
                float(str(val).replace(",", ""))
                numeric_count += 1
            except ValueError:
                if any(c.isdigit() for c in str(val)):
                    numeric_count += 0.5
    if total_values > 0:
        score += (numeric_count / total_values) * 15

    # 5. Unit detection reliability (10 points)
    max_score += 10
    if unit_source == "cm":
        score += 10  # Explicitly detected as CM
    elif unit_source == "inches":
        score += 8  # Explicitly detected as inches (will be converted)
    else:
        score += 3  # Heuristic

    # 6. Discovery method reliability (10 points)
    max_score += 10
    discovery_scores = {
        "found_clicked": 10,
        "found_inline": 8,
        "found_accordion": 8,
        "found_attr": 7,
        "found_iframe": 7,
        "known_store": 10,
        "not_found": 0,
    }
    score += discovery_scores.get(discovery_method, 3)

    return round(min(score / max_score, 1.0), 2)
