"""
HTTP client for the browser microservice.

Calls the browser-service to scrape JS-rendered pages.
Handles connection errors and timeouts gracefully.
"""

import os
import logging

import requests

logger = logging.getLogger(__name__)

BROWSER_SERVICE_URL = os.getenv("BROWSER_SERVICE_URL", "http://localhost:3000")


def scrape_via_browser(url: str, store: str = "",
                       timeout_ms: int = 60000,
                       use_ocr: bool = False) -> dict:
    """
    Call the browser microservice to scrape a JS-rendered page.

    Returns dict with keys: success, product_title, unit, headers, rows,
    confidence, detection_method, image_urls, error, duration_ms
    """
    payload = {
        "url": url,
        "store": store,
        "timeout_ms": timeout_ms,
        "use_ocr": use_ocr,
    }

    # HTTP timeout = scrape timeout + 10s buffer for network overhead
    http_timeout = timeout_ms / 1000 + 10

    try:
        resp = requests.post(
            f"{BROWSER_SERVICE_URL}/scrape",
            json=payload,
            timeout=http_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    except requests.ConnectionError:
        logger.warning(f"Browser service unavailable at {BROWSER_SERVICE_URL}")
        return {
            "success": False,
            "error": "Browser service unavailable",
        }

    except requests.Timeout:
        logger.warning(f"Browser service timeout for {url}")
        return {
            "success": False,
            "error": f"Browser service timeout after {http_timeout}s",
        }

    except requests.HTTPError as e:
        logger.error(f"Browser service HTTP error: {e}")
        return {
            "success": False,
            "error": f"Browser service error: {e.response.status_code}",
        }

    except Exception as e:
        logger.error(f"Browser client error: {e}")
        return {
            "success": False,
            "error": str(e),
        }


def browser_service_healthy() -> bool:
    """Check if the browser service is reachable."""
    try:
        resp = requests.get(f"{BROWSER_SERVICE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
