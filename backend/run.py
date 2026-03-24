"""
Size Chart Scraper — CLI entry point.

Usage:
    python3 run.py <product_url>
    python3 run.py <url1> <url2> <url3> ...
    python3 run.py <store_url> --mode store --max-products 50
    python3 run.py <url> --headless --format json
    python3 run.py <url> --ocr

Options:
    --mode          "product" (default) or "store"
    --max-products  Max products in store mode (default: 20)
    --output        Output filename prefix (default: size_charts)
    --format        "json", "csv", or "both" (default: both)
    --delay         Delay between requests in seconds (default: 1.0)
    --headless      Enable browser service for JS-rendered content
    --ocr           Enable GPU-powered OCR for image-based size charts
"""

from scraper import main

if __name__ == "__main__":
    main()
