"""
Export module — JSON and CSV output from SizeChart objects.
"""

import csv
import json
import os
from .models import SizeChart


def export_json(charts: list[SizeChart], filepath: str):
    """Export charts as JSON array."""
    data = [c.to_dict() for c in charts]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved JSON → {filepath}")


def export_csv(charts: list[SizeChart], filepath: str):
    """Export charts as flattened CSV (one row per size per product)."""
    all_rows = []
    for chart in charts:
        all_rows.extend(chart.to_flat_rows())

    if not all_rows:
        print(f"  No data to export to CSV")
        return

    # Collect all column names (static + dynamic measurement columns)
    static_cols = [
        "product_url", "product_title", "store_domain", "detection_method",
        "chart_type", "unit", "category", "confidence", "size",
    ]
    measurement_cols = set()
    for row in all_rows:
        for key in row:
            if key not in static_cols:
                measurement_cols.add(key)

    fieldnames = static_cols + sorted(measurement_cols)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  Saved CSV → {filepath}")


def export_normalized(charts: list[SizeChart], filepath: str):
    """Export normalized charts merged by category."""
    by_category = {}
    for chart in charts:
        if not chart.rows:
            continue
        cat = chart.category
        if cat not in by_category:
            by_category[cat] = {
                "category": cat,
                "unit": chart.unit,
                "headers": list(chart.headers),
                "sizes": {},
            }
        # Merge headers
        existing_headers = set(by_category[cat]["headers"])
        for h in chart.headers:
            if h not in existing_headers:
                by_category[cat]["headers"].append(h)
                existing_headers.add(h)

        # Merge sizes
        for row in chart.rows:
            if row.size not in by_category[cat]["sizes"]:
                by_category[cat]["sizes"][row.size] = {}
            by_category[cat]["sizes"][row.size].update(row.measurements)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(by_category, f, indent=2, ensure_ascii=False)

    print(f"  Saved normalized → {filepath}")


def charts_to_dataframe(charts: list[SizeChart]):
    """Convert charts to a pandas DataFrame (backward compatibility)."""
    import pandas as pd
    all_rows = []
    for chart in charts:
        for r in chart.rows:
            row = {
                "Product": chart.product_title,
                "Unit": chart.unit,
                "Size": r.size,
            }
            row.update(r.measurements)
            all_rows.append(row)
    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
