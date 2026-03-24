"""
Static detectors — all 7 detection methods running against HTML + JSON.

No browser required. Each detector returns a list of SizeChart objects.
"""

import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup, Tag

from .models import SizeChart, MeasurementRow
from .table_parser import (
    extract_rows_from_table, extract_rows_from_html,
    auto_orient, score_as_size_chart, build_measurement_rows,
    detect_unit, detect_chart_type, guess_category, _skip_title_rows,
)
from .static_fetcher import (
    fetch_page_html, fetch_page_json, parse_html,
    get_base_url, resolve_url,
)


# ── Shared helpers ──────────────────────────────────────────────────

SIZE_CHART_KEYWORDS = re.compile(
    r'size\s*chart|size\s*guide|sizing\s*(chart|guide)|measurement\s*(chart|guide)|fit\s*guide',
    re.IGNORECASE,
)

PRODUCT_DESC_SELECTORS = [
    ".product__description",
    ".product-description",
    ".product-single__description",
    "[class*='product-desc']",
    ".rte",
    "#product-description",
]


def _find_product_description(soup: BeautifulSoup) -> Tag | None:
    """Find the product description area."""
    for sel in PRODUCT_DESC_SELECTORS:
        el = soup.select_one(sel)
        if el:
            return el
    return None


def _make_chart(
    rows_2d: list[list[str]],
    product_url: str,
    product_title: str,
    detection_method: str,
    raw_html: str = "",
    confidence_boost: float = 0.0,
    page_text: str = "",
) -> SizeChart | None:
    """
    Common pipeline: orient → validate → build MeasurementRows → detect unit/type/category.
    Returns a SizeChart or None if the table isn't a size chart.
    """
    rows_2d = auto_orient(rows_2d)
    confidence = score_as_size_chart(rows_2d)
    if confidence < 0.3:
        return None

    headers, mrows = build_measurement_rows(rows_2d)
    if not mrows:
        return None

    confidence = min(confidence + confidence_boost, 1.0)
    domain = urlparse(product_url).netloc

    chart = SizeChart(
        product_url=product_url,
        product_title=product_title,
        store_domain=domain,
        detection_method=detection_method,
        chart_type=detect_chart_type(headers, page_text),
        unit=detect_unit(headers, mrows, page_text),
        category=guess_category(product_title),
        headers=headers,
        rows=mrows,
        raw_html=raw_html[:2000],
        confidence=round(confidence, 2),
    )
    return chart


# ── Method 1: Image in product description ──────────────────────────

def detect_images(soup: BeautifulSoup, body_html: str, product_url: str,
                   product_title: str, use_ocr: bool = False) -> list[SizeChart]:
    """
    Find size chart images in the product description.
    If use_ocr=True, runs GPU-powered OCR to extract actual table data from images.
    """
    image_urls = []
    base = get_base_url(product_url)

    img_keyword_pattern = re.compile(r'size|sizing|measurement|fit.guide|chart', re.IGNORECASE)

    # Search rendered page
    desc = _find_product_description(soup)
    search_areas = [desc] if desc else [soup]

    # Also search body_html from JSON
    if body_html:
        search_areas.append(parse_html(body_html))

    for area in search_areas:
        if area is None:
            continue
        for img in area.find_all("img"):
            alt = img.get("alt", "")
            src = img.get("src", "") or img.get("data-src", "")
            title_attr = img.get("title", "")
            combined = f"{alt} {src} {title_attr}"
            if img_keyword_pattern.search(combined) and src:
                full_url = resolve_url(base, src)
                if full_url not in image_urls:
                    image_urls.append(full_url)

    if not image_urls:
        return []

    # If OCR is enabled, try to extract structured data from the images
    if use_ocr:
        try:
            from .ocr import ocr_size_charts
            ocr_charts = ocr_size_charts(image_urls, product_url, product_title)
            if ocr_charts:
                return ocr_charts
            print(f"  [ocr] No data extracted from images, returning image-only result")
        except Exception as e:
            print(f"  [ocr] OCR failed: {e}, returning image-only result")

    # Fallback: return image URLs without structured data
    domain = urlparse(product_url).netloc
    return [SizeChart(
        product_url=product_url,
        product_title=product_title,
        store_domain=domain,
        detection_method="image_in_description",
        category=guess_category(product_title),
        image_urls=image_urls,
        confidence=0.4,
    )]


# ── Method 2: Inline HTML table in product description ──────────────

def detect_inline_tables(body_html: str, soup: BeautifulSoup,
                         product_url: str, product_title: str) -> list[SizeChart]:
    """Find <table> elements in the product description / body_html."""
    charts = []

    # Primary: body_html from JSON
    if body_html:
        tables_2d = extract_rows_from_html(body_html)
        for rows_2d in tables_2d:
            chart = _make_chart(
                rows_2d, product_url, product_title,
                "inline_html_table", raw_html=body_html[:2000],
            )
            if chart:
                charts.append(chart)

    # Secondary: rendered product description
    desc = _find_product_description(soup)
    if desc:
        for table in desc.find_all("table"):
            rows_2d = extract_rows_from_table(table)
            if len(rows_2d) >= 2:
                chart = _make_chart(
                    rows_2d, product_url, product_title,
                    "inline_html_table", raw_html=str(table)[:2000],
                )
                if chart:
                    charts.append(chart)

    return charts


# ── Method 3: Dedicated CMS page ───────────────────────────────────

def detect_cms_pages(soup: BeautifulSoup, product_url: str, product_title: str) -> list[SizeChart]:
    """Find links to /pages/size-* and fetch + parse them."""
    charts = []
    base = get_base_url(product_url)
    seen_urls = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True).lower()

        # Skip fragment-only links (popup triggers, handled by Method 4)
        if href.startswith("#"):
            continue

        is_size_link = (
            re.search(r'/pages/size', href, re.IGNORECASE) or
            SIZE_CHART_KEYWORDS.search(text)
        )
        if not is_size_link:
            continue

        # Skip if href points to the same product page
        if "/products/" in href:
            continue

        full_url = resolve_url(base, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Try JSON endpoint first
        page_data = fetch_page_json(full_url)
        page_body = page_data.get("body_html", "")

        if page_body:
            tables_2d = extract_rows_from_html(page_body)
            for rows_2d in tables_2d:
                chart = _make_chart(
                    rows_2d, product_url, product_title,
                    "cms_page", raw_html=page_body[:2000],
                    confidence_boost=0.1,
                )
                if chart:
                    charts.append(chart)

        # Also fetch the rendered page if JSON had no tables
        if not charts:
            html, status = fetch_page_html(full_url)
            if status == 200 and html:
                page_soup = parse_html(html)
                content_areas = page_soup.select(".page-content, .rte, .shopify-section, main, article")
                for area in content_areas:
                    for table in area.find_all("table"):
                        rows_2d = extract_rows_from_table(table)
                        if len(rows_2d) >= 2:
                            chart = _make_chart(
                                rows_2d, product_url, product_title,
                                "cms_page", raw_html=str(table)[:2000],
                                confidence_boost=0.1,
                            )
                            if chart:
                                charts.append(chart)

    return charts


# ── Method 4: Metafield popup / collapsible blocks ──────────────────

POPUP_SELECTORS = [
    ".modal--size-chart",
    "#size-chart-modal",
    "[data-modal='size-chart']",
    ".popup--size-chart",
    ".product__size-chart",
    "[id*='size-chart']",
    "[id*='SizeChart']",
    "[class*='size-chart']",
    "[class*='sizeChart']",
    "[class*='size_chart']",
    ".modal-size-guide",
    "#modal-size-guide",
]

COLLAPSIBLE_SELECTORS = [
    ".accordion__content",
    ".collapsible-content",
    "[class*='collapsible']",
]


def detect_popups_and_collapsibles(soup: BeautifulSoup, product_url: str,
                                    product_title: str) -> list[SizeChart]:
    """Find size chart data in popup modals and collapsible blocks."""
    charts = []

    # Popup modals
    for sel in POPUP_SELECTORS:
        for el in soup.select(sel):
            for table in el.find_all("table"):
                rows_2d = extract_rows_from_table(table)
                if len(rows_2d) >= 2:
                    chart = _make_chart(
                        rows_2d, product_url, product_title,
                        "metafield_popup", raw_html=str(table)[:2000],
                        confidence_boost=0.15,
                    )
                    if chart:
                        charts.append(chart)

    # Collapsible blocks / accordions
    for sel in COLLAPSIBLE_SELECTORS:
        for el in soup.select(sel):
            # Check if the heading/trigger contains size keywords
            heading = ""
            prev = el.find_previous_sibling()
            if prev:
                heading = prev.get_text(strip=True).lower()

            # For <details> elements
            parent = el.find_parent("details")
            if parent:
                summary = parent.find("summary")
                if summary:
                    heading = summary.get_text(strip=True).lower()

            if not SIZE_CHART_KEYWORDS.search(heading) and "size" not in heading:
                continue

            for table in el.find_all("table"):
                rows_2d = extract_rows_from_table(table)
                if len(rows_2d) >= 2:
                    chart = _make_chart(
                        rows_2d, product_url, product_title,
                        "metafield_collapsible", raw_html=str(table)[:2000],
                        confidence_boost=0.1,
                    )
                    if chart:
                        charts.append(chart)

    # Also check <details> elements directly
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if not summary:
            continue
        summary_text = summary.get_text(strip=True).lower()
        if "size" not in summary_text and "fit" not in summary_text and "measurement" not in summary_text:
            continue
        for table in details.find_all("table"):
            rows_2d = extract_rows_from_table(table)
            if len(rows_2d) >= 2:
                chart = _make_chart(
                    rows_2d, product_url, product_title,
                    "metafield_collapsible", raw_html=str(table)[:2000],
                    confidence_boost=0.1,
                )
                if chart:
                    charts.append(chart)

    return charts


# ── Method 6: Liquid theme sections ─────────────────────────────────

THEME_SECTION_SELECTORS = [
    ".shopify-section [class*='size']",
    ".product-tabs [class*='size']",
    ".product__tab [class*='size']",
    "[data-section-type='size-chart']",
    ".tab-content [class*='size']",
    ".product-info__tab",
]


def detect_theme_sections(soup: BeautifulSoup, product_url: str,
                          product_title: str) -> list[SizeChart]:
    """Find size charts in Liquid theme sections and tabs."""
    charts = []

    for sel in THEME_SECTION_SELECTORS:
        for el in soup.select(sel):
            for table in el.find_all("table"):
                rows_2d = extract_rows_from_table(table)
                if len(rows_2d) >= 2:
                    chart = _make_chart(
                        rows_2d, product_url, product_title,
                        "liquid_theme_section", raw_html=str(table)[:2000],
                    )
                    if chart:
                        charts.append(chart)

    # Also check tabbed interfaces (common pattern: tab-1, tab-2, etc.)
    for tab in soup.select("[id^='tab-'], [class*='tab-panel'], [role='tabpanel']"):
        text = tab.get_text(strip=True).lower()
        if "size" not in text and "measurement" not in text:
            continue
        for table in tab.find_all("table"):
            rows_2d = extract_rows_from_table(table)
            if len(rows_2d) >= 2:
                chart = _make_chart(
                    rows_2d, product_url, product_title,
                    "liquid_theme_section", raw_html=str(table)[:2000],
                )
                if chart:
                    charts.append(chart)

    return charts


# ── Method 7: Third-party app widgets (static phase) ────────────────

APP_SELECTORS = {
    "app_kiwi_sizing": [".kiwi-size-chart", "#kiwi-sizing-chart", "[data-kiwi-sizing]", ".kiwi-sg"],
    "app_esc_size_charts": [".esc-size-guide", "#esc-size-guide", ".esc-size-chart-content"],
    "app_clean_size_charts": [".csc-size-chart", "#csc-modal", "[data-csc-chart]"],
    "app_avada_size_chart": [".avada-sc-modal", ".avada-size-chart"],
    "app_roartheme_size_chart": [".rtsc-size-chart", ".rt-size-chart"],
    "app_variant_desc_king": [".vdk-size-chart", "[data-vdk]"],
}

APP_SCRIPT_PATTERNS = {
    "app_kiwi_sizing": ["kiwi"],
    "app_esc_size_charts": ["esc-size", "eastside"],
    "app_clean_size_charts": ["clean-size"],
}


def detect_app_widgets(soup: BeautifulSoup, product_url: str,
                       product_title: str) -> list[SizeChart]:
    """Detect third-party app size chart widgets (static phase)."""
    charts = []
    detected_apps = set()

    # Phase 1: Check CSS selectors
    for app_name, selectors in APP_SELECTORS.items():
        for sel in selectors:
            for el in soup.select(sel):
                detected_apps.add(app_name)
                # Try to extract tables from within the app container
                for table in el.find_all("table"):
                    rows_2d = extract_rows_from_table(table)
                    if len(rows_2d) >= 2:
                        chart = _make_chart(
                            rows_2d, product_url, product_title,
                            app_name, raw_html=str(table)[:2000],
                        )
                        if chart:
                            charts.append(chart)

                # Also try div-based grids inside app containers
                if not charts:
                    rows_2d = _extract_div_grid(el)
                    if rows_2d and len(rows_2d) >= 2:
                        chart = _make_chart(
                            rows_2d, product_url, product_title,
                            app_name, raw_html=str(el)[:2000],
                        )
                        if chart:
                            charts.append(chart)

    # Phase 2: Script tag detection
    for script in soup.find_all("script", src=True):
        src = script["src"].lower()
        for app_name, patterns in APP_SCRIPT_PATTERNS.items():
            if any(p in src for p in patterns):
                detected_apps.add(app_name)

    # If app detected but no data extracted, create a placeholder chart
    # signaling that headless browser is needed
    if detected_apps and not charts:
        domain = urlparse(product_url).netloc
        for app_name in detected_apps:
            charts.append(SizeChart(
                product_url=product_url,
                product_title=product_title,
                store_domain=domain,
                detection_method=f"{app_name}_jsrendered",
                category=guess_category(product_title),
                confidence=0.3,
            ))

    return charts


def _extract_div_grid(container: Tag) -> list[list[str]]:
    """Try to extract a table-like structure from div-based grid layouts."""
    # Look for repeated row patterns
    row_candidates = container.select("[class*='row'], [class*='tr'], [class*='grid-row']")
    if len(row_candidates) < 2:
        # Fallback: direct children as cells in a grid
        children = [c for c in container.children if isinstance(c, Tag)]
        if len(children) < 4:
            return []
        # Heuristic: try to figure out columns from first few elements
        # This is limited without JS layout info, but try common patterns
        return []

    rows = []
    for row_el in row_candidates:
        cells = []
        for cell in row_el.find_all(["div", "span", "td", "th"]):
            if cell.find(["div", "span"]):
                continue  # Skip parent containers
            text = cell.get_text(strip=True)
            if text:
                cells.append(text)
        if cells:
            rows.append(cells)

    return rows if len(rows) >= 2 else []


# ── Detect if headless browser is needed ────────────────────────────

def needs_headless(soup: BeautifulSoup, charts: list[SizeChart]) -> bool:
    """
    Determine if we should fall back to headless browser.
    True if: no good charts found AND JS-rendered app was detected.
    """
    if charts and max(c.confidence for c in charts) >= 0.5:
        return False

    # Check for JS-rendered app placeholders
    for c in charts:
        if c.detection_method.endswith("_jsrendered"):
            return True

    # Check for empty app containers
    for selectors in APP_SELECTORS.values():
        for sel in selectors:
            el = soup.select_one(sel)
            if el and not el.find("table"):
                return True

    return False
