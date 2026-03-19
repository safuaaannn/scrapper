"""
Size Chart Scraper — CLI entry point.

Usage:
    python3 run.py <product_url>
    python3 run.py <url1> <url2> <url3> ...

Works with any product URL. Optimized scrapers for known stores,
universal scraper for everything else.
"""
import asyncio
from scraper import main

if __name__ == "__main__":
    asyncio.run(main())
