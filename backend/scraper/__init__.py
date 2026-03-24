"""
Size Chart Scraper — Static-First + Browser Service Fallback

Architecture:
    1. Static scraping (requests + BS4) — fast, ~1 sec/product
       Runs all 7 detection methods against HTML + Shopify JSON
    2. Browser service fallback — HTTP call to browser microservice
       for JS-rendered content (store-specific + universal scrapers)

Usage:
    # Sync (static + browser service fallback)
    charts = scrape_url("https://store.com/products/tee")

    # Sync (static only, no browser needed)
    charts = scrape_url_static("https://store.com/products/tee")
"""

import os
import sys
import time
from urllib.parse import urlparse

import pandas as pd

from .config import OUTPUT_DIR
from .models import SizeChart, MeasurementRow
from .static_pipeline import scrape_static, deduplicate
from .export import export_json, export_csv, export_normalized, charts_to_dataframe
from . import browser_client


def detect_store(url: str) -> str:
    """Detect known store from URL hostname."""
    host = urlparse(url).netloc.lower()
    store_map = {
        "snitch.co.in": "snitch",
        "snitch.com": "snitch",
        "fashionnova.com": "fashionnova",
        "libas.in": "libas",
        "thehouseofrare.com": "rarerabbit",
        "gymshark.com": "gymshark",
        "bombayshirts.com": "bombayshirts",
        "theloom.in": "theloom",
        "outdoorvoices.com": "outdoorvoices",
        "goodamerican.com": "goodamerican",
    }
    for domain, store in store_map.items():
        if domain in host:
            return store
    return ""


def scrape_url_static(url: str, use_ocr: bool = False) -> list[SizeChart]:
    """
    Static-only scraping — no browser needed.
    Returns list of SizeChart objects.
    """
    charts, _ = scrape_static(url, use_ocr=use_ocr)
    return charts


def scrape_url(url: str, headless: bool = True,
               use_ocr: bool = False) -> list[SizeChart]:
    """
    Full scraping pipeline (synchronous):
    1. Static scraping (fast, no browser)
    2. If static finds good data (confidence >= 0.5), return it
    3. If headless enabled and static was insufficient, call browser service
    4. If use_ocr=True, OCR is applied to any image-based size charts

    Returns list of SizeChart objects.
    """
    print(f"\n{'='*60}")
    print(f"Scraping: {url}")
    print(f"{'='*60}")

    # Layer 1: Static scraping (fast path)
    charts, should_try_headless = scrape_static(url, use_ocr=use_ocr)
    data_charts = [c for c in charts if c.rows]

    if data_charts and max(c.confidence for c in data_charts) >= 0.5:
        print(f"  Static scraping found good data, skipping browser service")
        return charts

    # Layer 2: Browser service fallback
    if headless and (should_try_headless or not data_charts):
        store = detect_store(url)
        print(f"\n  [browser-service] Calling browser service...")
        result = browser_client.scrape_via_browser(
            url, store=store, use_ocr=use_ocr,
        )

        if result.get("success"):
            print(f"  [browser-service] Got data (confidence: {result.get('confidence', 0)})")
            chart = _response_to_sizechart(result, url)
            charts.append(chart)
            charts = deduplicate(charts)
        elif result.get("error") == "Browser service unavailable":
            print(f"  [browser-service] Service unavailable, returning static results only")
        else:
            error = result.get("error", "Unknown error")
            print(f"  [browser-service] Failed: {error}")

            # Check if browser returned image URLs without table data
            if result.get("image_urls"):
                domain = urlparse(url).netloc
                from .table_parser import guess_category
                img_chart = SizeChart(
                    product_url=url,
                    product_title=result.get("product_title", ""),
                    store_domain=domain,
                    detection_method="browser_image",
                    category=guess_category(""),
                    image_urls=result["image_urls"],
                    confidence=0.4,
                )
                charts.append(img_chart)

    if not any(c.rows for c in charts):
        print(f"  No size chart data found.")

    return charts


def _response_to_sizechart(result: dict, url: str) -> SizeChart:
    """Convert browser service JSON response to a SizeChart object."""
    domain = urlparse(url).netloc
    from .table_parser import guess_category

    rows = []
    for r in result.get("rows", []):
        rows.append(MeasurementRow(
            size=r.get("size", ""),
            measurements=r.get("measurements", {}),
        ))

    return SizeChart(
        product_url=url,
        product_title=result.get("product_title", ""),
        store_domain=domain,
        detection_method=result.get("detection_method", "browser_service"),
        unit=result.get("unit", "cm"),
        category=guess_category(result.get("product_title", "")),
        headers=result.get("headers", []),
        rows=rows,
        image_urls=result.get("image_urls", []),
        confidence=result.get("confidence", 0.7),
    )


def scrape_store(store_url: str, max_products: int = 20,
                 delay: float = 1.0, headless: bool = False,
                 use_ocr: bool = False) -> list[SizeChart]:
    """
    Whole store mode: discover products via /products.json and scrape each.
    """
    from .static_fetcher import fetch_store_products, get_base_url

    print(f"\nDiscovering products from {store_url}...")
    products = fetch_store_products(store_url, max_products=max_products, delay=delay)
    print(f"Found {len(products)} products")

    base = get_base_url(store_url)
    all_charts = []

    for i, product in enumerate(products):
        handle = product.get("handle", "")
        if not handle:
            continue
        product_url = f"{base}/products/{handle}"
        print(f"\n[{i+1}/{len(products)}] {product.get('title', handle)}")

        try:
            charts = scrape_url(product_url, headless=headless, use_ocr=use_ocr)
            all_charts.extend(charts)
        except Exception as e:
            print(f"  ERROR: {e}")

        if i < len(products) - 1:
            time.sleep(delay)

    return all_charts


def main():
    """CLI entry point (synchronous)."""
    import argparse

    parser = argparse.ArgumentParser(description="Size Chart Scraper")
    parser.add_argument("url", nargs="+", help="Product URL(s) or store URL")
    parser.add_argument("--mode", choices=["product", "store"], default="product",
                        help="Scraping mode (default: product)")
    parser.add_argument("--max-products", type=int, default=20,
                        help="Max products in store mode (default: 20)")
    parser.add_argument("--output", default="size_charts",
                        help="Output filename prefix (default: size_charts)")
    parser.add_argument("--format", choices=["json", "csv", "both"], default="both",
                        help="Output format (default: both)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Delay between requests in seconds (default: 1.0)")
    parser.add_argument("--headless", action="store_true",
                        help="Enable browser service for JS-rendered content")
    parser.add_argument("--ocr", action="store_true",
                        help="Enable GPU-powered OCR for image-based size charts")

    args = parser.parse_args()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if args.ocr:
        print("  [ocr] GPU OCR enabled — models will load on first image detection")

    if args.mode == "store":
        all_charts = scrape_store(
            args.url[0], max_products=args.max_products,
            delay=args.delay, headless=args.headless,
            use_ocr=args.ocr,
        )
    else:
        all_charts = []
        for url in args.url:
            charts = scrape_url(url, headless=args.headless, use_ocr=args.ocr)
            all_charts.extend(charts)

    # Print results
    data_charts = [c for c in all_charts if c.rows]
    if data_charts:
        print(f"\n{'='*60}")
        print(f"Results: {len(data_charts)} size chart(s) found")
        print(f"{'='*60}")
        for chart in data_charts:
            print(f"\n  [{chart.detection_method}] {chart.product_title}")
            print(f"  Confidence: {chart.confidence} | Unit: {chart.unit} | "
                  f"Type: {chart.chart_type} | Category: {chart.category}")
            print(f"  Headers: {chart.headers}")
            for r in chart.rows[:3]:
                print(f"    {r.size}: {r.measurements}")
            if len(chart.rows) > 3:
                print(f"    ... and {len(chart.rows) - 3} more rows")

        # Export
        prefix = os.path.join(OUTPUT_DIR, args.output)
        if args.format in ("json", "both"):
            export_json(data_charts, f"{prefix}.json")
        if args.format in ("csv", "both"):
            export_csv(data_charts, f"{prefix}.csv")

        if len(data_charts) > 1:
            export_normalized(data_charts, f"{prefix}_normalized.json")
    else:
        image_charts = [c for c in all_charts if c.image_urls]
        if image_charts:
            print(f"\nFound {len(image_charts)} image-based chart(s) (no structured data):")
            for c in image_charts:
                for img in c.image_urls:
                    print(f"  {img}")
        else:
            print("\nNo size chart data found.")
