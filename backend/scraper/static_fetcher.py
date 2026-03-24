"""
Static HTTP fetch layer — requests + BeautifulSoup.

Dual fetch: rendered HTML + Shopify JSON API, no browser needed.
"""

import time
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

from .config import HEADERS

# Persistent session for connection pooling
_session = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "text/html,application/xhtml+xml,application/json",
        })
    return _session


def fetch_page_html(url: str, timeout: int = 15) -> tuple[str, int]:
    """
    Fetch rendered HTML of a page.
    Returns (html_string, status_code). Returns ("", status) on failure.
    """
    session = _get_session()
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(retry_after)
            resp = session.get(url, timeout=timeout, allow_redirects=True)
        return resp.text, resp.status_code
    except requests.RequestException:
        return "", 0


def fetch_product_json(product_url: str, timeout: int = 15) -> dict:
    """
    Fetch Shopify product JSON from /products/<handle>.json.
    Returns the product dict or empty dict on failure.
    """
    json_url = product_url.split("?")[0]
    if not json_url.endswith(".json"):
        json_url += ".json"

    session = _get_session()
    try:
        resp = session.get(json_url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("product", {})
    except (requests.RequestException, ValueError):
        pass
    return {}


def fetch_page_json(page_url: str, timeout: int = 15) -> dict:
    """
    Fetch Shopify CMS page JSON from /pages/<handle>.json.
    Returns the page dict or empty dict on failure.
    """
    json_url = page_url.split("?")[0].rstrip("/")
    if not json_url.endswith(".json"):
        json_url += ".json"

    session = _get_session()
    try:
        resp = session.get(json_url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("page", {})
    except (requests.RequestException, ValueError):
        pass
    return {}


def fetch_store_products(store_url: str, max_products: int = 20, delay: float = 1.0) -> list[dict]:
    """
    Discover products via /products.json pagination.
    Returns list of product dicts up to max_products.
    """
    base = store_url.rstrip("/")
    session = _get_session()
    products = []
    page = 1

    while len(products) < max_products:
        url = f"{base}/products.json?limit=50&page={page}"
        try:
            resp = session.get(url, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            batch = data.get("products", [])
            if not batch:
                break
            products.extend(batch)
            page += 1
            if len(batch) < 50:
                break
            time.sleep(delay)
        except (requests.RequestException, ValueError):
            break

    return products[:max_products]


def parse_html(html: str) -> BeautifulSoup:
    """Parse HTML string into BeautifulSoup."""
    return BeautifulSoup(html, "lxml")


def get_base_url(url: str) -> str:
    """Extract base URL (scheme + domain)."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def resolve_url(base_url: str, href: str) -> str:
    """Resolve a possibly-relative URL against a base."""
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base_url, href)


def is_password_protected(html: str) -> bool:
    """Check if the page is a Shopify password page."""
    soup = parse_html(html)
    form = soup.find("form", action="/password")
    return form is not None
