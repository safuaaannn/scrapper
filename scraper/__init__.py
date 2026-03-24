"""
Size Chart Scraper — Universal + Store-Specific

Takes any product URL → finds the size chart → extracts measurements in CM.

Usage:
    from scraper import scrape_url
    df = await scrape_url("https://example.com/products/some-product", browser=browser)
"""

import asyncio
import os
import sys
from urllib.parse import urlparse

import pandas as pd

from .config import OUTPUT_DIR, MAX_PARALLEL
from .stores import STORE_SCRAPERS
from .universal.pipeline import scrape_universal
from .shopify_api import try_shopify_api


def detect_store(url: str) -> str:
    """Detect known store from URL hostname."""
    host = urlparse(url).netloc.lower()
    store_map = {
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
        print(f"\nStore: {store.upper()} (known)")
        print(f"URL:   {url}")
        try:
            df = await STORE_SCRAPERS[store](url, browser=browser)
            if not df.empty:
                return df
            print(f"  Known scraper returned empty, falling through to universal...")
        except Exception as e:
            print(f"  Known scraper failed: {e}, falling through to universal...")

    # Layer 2: Universal scraper
    print(f"\nStore: UNIVERSAL")
    print(f"URL:   {url}")
    try:
        df, confidence = await scrape_universal(url, browser=browser)
        if not df.empty and confidence >= 0.3:
            print(f"  Universal scraper succeeded (confidence: {confidence})")
            return df
        elif not df.empty:
            print(f"  Universal scraper low confidence ({confidence}), trying Shopify API...")
        else:
            print(f"  Universal scraper found nothing, trying Shopify API...")
    except Exception as e:
        print(f"  Universal scraper failed: {e}, trying Shopify API...")

    # Layer 3: Shopify API fallback
    if "/products/" in url:
        try:
            df, confidence = await try_shopify_api(url, browser=browser)
            if not df.empty:
                print(f"  Shopify API fallback succeeded (confidence: {confidence})")
                return df
        except Exception as e:
            print(f"  Shopify API fallback failed: {e}")

    print(f"  No size chart data found.")
    return pd.DataFrame()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scraper <url1> [url2] [url3] ...")
        sys.exit(1)

    urls = sys.argv[1:]
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

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

        await browser.close()

    all_dfs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"\n  ERROR scraping {urls[i]}: {result}\n")
            continue
        df = result
        if df.empty:
            print("  No size chart data found.\n")
            continue

        all_dfs.append(df)
        print(f"\n  Size Chart ({len(df)} sizes, all measurements in CM):\n")
        print(df.to_string(index=False))
        print()

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        filepath = os.path.join(OUTPUT_DIR, "size_charts.csv")
        combined.to_csv(filepath, index=False)
        print(f"Saved → {filepath}")
