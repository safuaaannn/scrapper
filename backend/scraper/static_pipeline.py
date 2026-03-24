"""
Static scraping pipeline — runs all 7 detectors without a browser.

This is the primary (fast) scraping path. Falls back to Playwright only when needed.
"""

import re
from urllib.parse import urlparse

from .models import SizeChart
from .static_fetcher import (
    fetch_page_html, fetch_product_json, parse_html, is_password_protected,
)
from .detectors import (
    detect_images,
    detect_inline_tables,
    detect_cms_pages,
    detect_popups_and_collapsibles,
    detect_theme_sections,
    detect_app_widgets,
    needs_headless,
)


def _extract_title_from_html(soup) -> str:
    """Extract product title from HTML."""
    for sel in ["h1", "[data-testid='product-title']", ".product__title",
                "[class*='product-title']", "[class*='ProductTitle']"]:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True)
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    return ""


def _title_from_url(url: str) -> str:
    """Fallback: extract title from product URL."""
    if "/products/" in url:
        handle = url.split("/products/")[-1].split("?")[0]
        return handle.replace("-", " ").title()
    return url.rstrip("/").split("/")[-1].replace("-", " ").title()


def deduplicate(charts: list[SizeChart]) -> list[SizeChart]:
    """
    Remove duplicate charts found by different detectors.
    Key: (tuple(headers), first_row_size, row_count)
    Keep highest confidence version.
    """
    seen = {}
    for chart in sorted(charts, key=lambda c: c.confidence, reverse=True):
        if not chart.rows:
            # Image-only or placeholder charts — keep by detection_method
            key = ("__no_data__", chart.detection_method)
        else:
            key = (
                tuple(chart.headers),
                chart.rows[0].size if chart.rows else "",
                len(chart.rows),
            )
        if key not in seen:
            seen[key] = chart

    return sorted(seen.values(), key=lambda c: c.confidence, reverse=True)


def scrape_static(product_url: str, use_ocr: bool = False) -> tuple[list[SizeChart], bool]:
    """
    Run all static detectors on a product URL.

    Args:
        product_url: The product page URL to scrape
        use_ocr: If True, run GPU-powered OCR on detected size chart images

    Returns:
        (charts, should_try_headless)
        charts: deduplicated list of SizeChart objects
        should_try_headless: True if headless browser should be tried
    """
    print(f"  [static] Fetching page and JSON...")

    # Dual fetch
    html, status = fetch_page_html(product_url)
    if status == 0:
        print(f"  [static] Failed to fetch page")
        return [], True

    if status in (403, 404):
        print(f"  [static] HTTP {status}, skipping")
        return [], False

    if is_password_protected(html):
        print(f"  [static] Store is password-protected")
        return [], False

    soup = parse_html(html)

    # Fetch JSON (best-effort, may fail for non-Shopify)
    product_json = {}
    if "/products/" in product_url:
        product_json = fetch_product_json(product_url)

    body_html = product_json.get("body_html", "")
    product_title = product_json.get("title", "") or _extract_title_from_html(soup)
    if not product_title:
        product_title = _title_from_url(product_url)

    print(f"  [static] Product: {product_title}")

    # Run all detectors
    all_charts = []

    # Method 7 first (app widgets) — highest priority per spec
    print(f"  [static] Checking app widgets...")
    all_charts.extend(detect_app_widgets(soup, product_url, product_title))

    # Method 6: Theme sections
    print(f"  [static] Checking theme sections...")
    all_charts.extend(detect_theme_sections(soup, product_url, product_title))

    # Method 4: Popup/collapsible
    print(f"  [static] Checking popups and collapsibles...")
    all_charts.extend(detect_popups_and_collapsibles(soup, product_url, product_title))

    # Method 3: CMS page links
    print(f"  [static] Checking CMS page links...")
    all_charts.extend(detect_cms_pages(soup, product_url, product_title))

    # Method 2: Inline tables in description
    print(f"  [static] Checking inline tables...")
    all_charts.extend(detect_inline_tables(body_html, soup, product_url, product_title))

    # Method 1: Images (with optional OCR)
    print(f"  [static] Checking for chart images{' (OCR enabled)' if use_ocr else ''}...")
    all_charts.extend(detect_images(soup, body_html, product_url, product_title, use_ocr=use_ocr))

    # Deduplicate
    charts = deduplicate(all_charts)

    # Determine if headless is needed
    try_headless = needs_headless(soup, charts)

    data_charts = [c for c in charts if c.rows]
    print(f"  [static] Found {len(data_charts)} chart(s) with data, "
          f"{len(charts) - len(data_charts)} image/placeholder(s)")
    if data_charts:
        best = max(data_charts, key=lambda c: c.confidence)
        print(f"  [static] Best confidence: {best.confidence} via {best.detection_method}")

    return charts, try_headless
