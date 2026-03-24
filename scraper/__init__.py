"""
Size Chart Scraper — Universal + Store-Specific

Takes any product URL → finds the size chart → extracts measurements in CM.

Usage:
    from scraper import scrape_url
    df = await scrape_url("https://example.com/products/some-product", browser=browser)
"""

import asyncio
import logging
import os
import sys
from urllib.parse import urlparse

import pandas as pd

from .config import OUTPUT_DIR, MAX_PARALLEL, BROWSER_ARGS
from .helpers import launch_browser
from .stores import STORE_SCRAPERS
from .universal.pipeline import scrape_universal
from .shopify_api import try_shopify_api

log = logging.getLogger(__name__)


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
    return "unknown"


async def scrape_url(url: str, browser=None) -> pd.DataFrame:
    """
    Scrape size chart from any product URL.

    1. If URL matches a known store → use optimized store-specific scraper
    2. Otherwise → use universal scraper
    3. If universal fails → try Shopify API fallback

    Returns a DataFrame with columns: Product, Unit, Size, + measurements.
    """
    store = detect_store(url)

    # Layer 1: Known store scraper
    if store in STORE_SCRAPERS:
        log.info("Store: %s (known) — %s", store.upper(), url)
        try:
            df = await STORE_SCRAPERS[store](url, browser=browser)
            if not df.empty:
                return df
            log.info("Known scraper returned empty, falling through to universal...")
        except Exception as e:
            log.warning("Known scraper failed: %s, falling through to universal...", e)

    # Layer 2: Universal scraper
    log.info("Store: UNIVERSAL — %s", url)
    try:
        df, confidence = await scrape_universal(url, browser=browser)
        if not df.empty and confidence >= 0.3:
            log.info("Universal scraper succeeded (confidence: %.2f)", confidence)
            return df
        elif not df.empty:
            log.info("Universal scraper low confidence (%.2f), trying Shopify API...", confidence)
        else:
            log.info("Universal scraper found nothing, trying Shopify API...")
    except Exception as e:
        log.warning("Universal scraper failed: %s, trying Shopify API...", e)

    # Layer 3: Shopify API fallback
    if "/products/" in url:
        try:
            df, confidence = await try_shopify_api(url, browser=browser)
            if not df.empty:
                log.info("Shopify API fallback succeeded (confidence: %.2f)", confidence)
                return df
        except Exception as e:
            log.warning("Shopify API fallback failed: %s", e)

    log.info("No size chart data found for %s", url)
    return pd.DataFrame()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python -m scraper <url1> [url2] [url3] ...")
        sys.exit(1)

    urls = sys.argv[1:]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    pw, browser = await launch_browser()
    try:
        if len(urls) == 1:
            results = [await scrape_url(urls[0], browser=browser)]
        else:
            sem = asyncio.Semaphore(MAX_PARALLEL)

            async def bounded_scrape(url):
                async with sem:
                    return await scrape_url(url, browser=browser)

            results = await asyncio.gather(
                *[bounded_scrape(url) for url in urls],
                return_exceptions=True,
            )
    finally:
        await browser.close()
        await pw.stop()

    all_dfs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error("ERROR scraping %s: %s", urls[i], result)
            continue
        if result.empty:
            log.info("No size chart data found for %s", urls[i])
            continue

        all_dfs.append(result)
        print(f"\n  Size Chart ({len(result)} sizes, all measurements in CM):\n")
        print(result.to_string(index=False))
        print()

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        filepath = os.path.join(OUTPUT_DIR, "size_charts.csv")
        combined.to_csv(filepath, index=False)
        print(f"Saved → {filepath}")
