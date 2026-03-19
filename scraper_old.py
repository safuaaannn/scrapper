"""
Backward-compatible wrapper — imports from the new scraper package.

Usage:
    python3 scraper.py <product_url>
    python3 scraper.py <url1> <url2> <url3> ...
"""
import asyncio
from scraper import scrape_url, main

if __name__ == "__main__":
    asyncio.run(main())
