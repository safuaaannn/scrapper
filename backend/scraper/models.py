"""
Data models for size chart scraper.

SizeChart and MeasurementRow — the normalized output schema.
"""

from dataclasses import dataclass, field


@dataclass
class MeasurementRow:
    """A single row in a size chart — one size with its measurements."""
    size: str                    # "XS", "S", "M", "L", "XL", "28", "30", "8-10"
    measurements: dict = field(default_factory=dict)  # {"Chest": "38-40", "Waist": "32-34"}


@dataclass
class SizeChart:
    """Normalized output for one size chart found on a product page."""
    product_url: str = ""
    product_title: str = ""
    store_domain: str = ""
    detection_method: str = ""      # e.g. "inline_html_table", "cms_page", "app_kiwi_sizing"
    chart_type: str = "unknown"     # "body_measurements" | "garment_measurements" | "unknown"
    unit: str = "unknown"           # "inches" | "cm" | "mixed" | "unknown"
    category: str = "general"       # "tops" | "bottoms" | "dresses" | "shoes" | "general"
    headers: list = field(default_factory=list)
    rows: list = field(default_factory=list)        # list[MeasurementRow]
    raw_html: str = ""              # First 2000 chars of source HTML
    image_urls: list = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "product_url": self.product_url,
            "product_title": self.product_title,
            "store_domain": self.store_domain,
            "detection_method": self.detection_method,
            "chart_type": self.chart_type,
            "unit": self.unit,
            "category": self.category,
            "headers": self.headers,
            "rows": [{"size": r.size, "measurements": r.measurements} for r in self.rows],
            "image_urls": self.image_urls,
            "confidence": self.confidence,
        }

    def to_flat_rows(self) -> list[dict]:
        """Flatten to CSV-style rows: one row per size."""
        flat = []
        for r in self.rows:
            row = {
                "product_url": self.product_url,
                "product_title": self.product_title,
                "store_domain": self.store_domain,
                "detection_method": self.detection_method,
                "chart_type": self.chart_type,
                "unit": self.unit,
                "category": self.category,
                "confidence": self.confidence,
                "size": r.size,
            }
            row.update(r.measurements)
            flat.append(row)
        return flat
