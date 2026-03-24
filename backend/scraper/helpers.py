"""Shared helper functions — backend-only (pure functions, no browser)."""

import re
from .config import INCH_TO_CM


def _inch_range_to_cm(val: str):
    """
    Convert inch range like '31 – 33"' or '33 1/2 – 35 1/2"' to cm.
    Returns averaged cm value, or original string if not parseable.
    """
    # Replace Unicode fraction characters with decimal equivalents
    UNICODE_FRACTIONS = {
        '½': '.5', '¼': '.25', '¾': '.75',
        '⅓': '.333', '⅔': '.667',
        '⅛': '.125', '⅜': '.375', '⅝': '.625', '⅞': '.875',
        '⅙': '.167', '⅚': '.833',
    }
    for uf, dec in UNICODE_FRACTIONS.items():
        val = val.replace(uf, dec)

    val = val.replace('\xa0', ' ').replace('\u201d', '').replace('"', '').strip()

    def parse_fraction(s):
        s = s.strip()
        match = re.match(r'(\d+)\s+(\d+)/(\d+)', s)
        if match:
            return int(match.group(1)) + int(match.group(2)) / int(match.group(3))
        try:
            return float(s)
        except ValueError:
            return None

    # Try range: "31 – 33" or "33 1/2 – 35 1/2"
    parts = re.split(r'\s*[–\-]\s*', val)
    if len(parts) == 2:
        low = parse_fraction(parts[0])
        high = parse_fraction(parts[1])
        if low is not None and high is not None:
            avg = (low + high) / 2
            return round(avg * INCH_TO_CM, 1)

    # Try single number
    num = parse_fraction(val)
    if num is not None:
        return round(num * INCH_TO_CM, 1)

    return val
