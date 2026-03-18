"""
Size Chart Scraper — Snitch, Fashion Nova & Libas
Give it a product URL → get the size chart in CM as CSV.

Usage:
    python3 scraper.py <product_url>
    python3 scraper.py <url1> <url2> <url3> ...

Examples:
    python3 scraper.py "https://www.snitch.com/men-shirts/lining-maroon-shirt/7355129528482/buy"
    python3 scraper.py "https://www.fashionnova.com/products/carina-snatched-pant-set-black"
    python3 scraper.py "https://www.libas.in/products/peach-self-design-silk-blend-straight-suit-set-33549o"
"""

import asyncio
import os
import re
import sys
from urllib.parse import urlparse

import pandas as pd

OUTPUT_DIR = "./size_chart_data"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

INCH_TO_CM = 2.54


def detect_store(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "snitch.com" in host:
        return "snitch"
    if "fashionnova.com" in host:
        return "fashionnova"
    if "libas.in" in host:
        return "libas"
    return "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# SNITCH
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_snitch(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Snitch product page.
    Opens the page, clicks "Size Chart", parses the vertical text data,
    and converts inches → cm.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=HEADERS["User-Agent"])

        print(f"  Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(8000)

        # Get product title from document.title (h1 is "Categories" on Snitch)
        title = await page.evaluate("""() => {
            let t = document.title || '';
            // Clean "Buy ... for men online in India" pattern
            t = t.replace(/^Buy\\s+/i, '').replace(/\\s+for\\s+(men|women).*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/")[-2] if "/buy" in product_url else ""

        # Click "Size Chart" button (retry up to 3 times — Next.js can be slow)
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('*')) {
                    const t = el.textContent.trim();
                    if ((t === 'Size Chart' || t === 'SIZE CHART') && el.children.length === 0) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                break
            await page.wait_for_timeout(3000)

        if not clicked:
            print("  ERROR: Could not find Size Chart button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Extract page text
        text = await page.evaluate("() => document.body.innerText")
        await browser.close()

    # Parse the size chart
    return parse_snitch_text(text, product_url, title)


def parse_snitch_text(text: str, product_url: str, title: str) -> pd.DataFrame:
    """
    Parse Snitch size chart from page text.
    Data is vertical: each value on its own line.
    Converts inches to cm.
    """
    lines = text.split("\n")

    # Find start of chart data (after "HOW TO MEASURE")
    start_idx = None
    for i, line in enumerate(lines):
        if "HOW TO MEASURE" in line.upper():
            start_idx = i
            break
    if start_idx is None:
        for i, line in enumerate(lines):
            if "measurements are in" in line.lower():
                start_idx = max(0, i - 200)
                break
    if start_idx is None:
        return pd.DataFrame()

    # Find end
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "measurements are in" in lines[i].lower():
            end_idx = i
            break

    # Detect unit
    unit = "inches"
    if end_idx < len(lines) and "cm" in lines[end_idx].lower():
        unit = "cm"

    # Collect non-empty lines
    chart_lines = [lines[i].strip() for i in range(start_idx, end_idx) if lines[i].strip()]

    # Parse vertical structure
    measurement_keywords = {
        "CHEST", "LENGTH", "SHOULDER", "SLEEVE", "WAIST", "HIP",
        "HIPS", "INSEAM", "BUST", "THIGH", "NECK",
    }
    sizes = []
    measurements = {}
    current_section = None

    for line in chart_lines:
        upper = line.upper()
        if upper in ("SIZE CHART", "HOW TO MEASURE", "INCHES", "CM"):
            continue
        if upper == "SIZE":
            current_section = "SIZE"
            continue
        if upper in measurement_keywords:
            current_section = upper
            measurements[current_section] = []
            continue
        if current_section == "SIZE":
            sizes.append(line)
        elif current_section and current_section in measurements:
            measurements[current_section].append(line)

    if not sizes or not measurements:
        return pd.DataFrame()

    # Build rows
    rows = []
    for i, size in enumerate(sizes):
        row = {"Size": size}
        for measure, values in measurements.items():
            if i < len(values):
                val = values[i]
                try:
                    numeric = float(val)
                    if unit == "inches":
                        numeric = round(numeric * INCH_TO_CM, 1)
                    row[measure.capitalize()] = numeric
                except ValueError:
                    row[measure.capitalize()] = val
        rows.append(row)

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# FASHION NOVA
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_fashionnova(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Fashion Nova product page.
    Clicks "View Size Guide", toggles to cm, parses the table.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=HEADERS["User-Agent"])

        print(f"  Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Get product title
        title = await page.evaluate("""() => {
            const el = document.querySelector('h1, [data-testid="product-title"]');
            return el ? el.textContent.trim() : '';
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "View Size Guide"
        clicked = await page.evaluate("""() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if (t === 'View Size Guide' && el.children.length <= 1) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        if not clicked:
            print("  ERROR: Could not find 'View Size Guide' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Click "cm" toggle
        await page.evaluate("""() => {
            for (const el of document.querySelectorAll('*')) {
                if (el.textContent.trim() === 'cm' && el.children.length === 0) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        await page.wait_for_timeout(2000)

        # Extract the measurements table text
        text = await page.evaluate("() => document.body.innerText")
        await browser.close()

    return parse_fashionnova_text(text, product_url, title)


def parse_fashionnova_text(text: str, product_url: str, title: str) -> pd.DataFrame:
    """
    Parse Fashion Nova size guide from page text.
    After clicking cm toggle, data appears as tab-separated table:
        Size\tBust\tWaist\tHips\tUK\tEU\tAUS
        XS\t81-84\t61-64\t89-91\t2/4\t32/34\t4/6
        ...
    """
    lines = text.split("\n")

    # Find the "Measurements" section
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "Measurements":
            start_idx = i
            break

    if start_idx is None:
        return pd.DataFrame()

    # Find the header row (contains "Size" and tab characters)
    header_idx = None
    headers = []
    for i in range(start_idx, min(start_idx + 10, len(lines))):
        line = lines[i].strip()
        if "Size" in line and "\t" in line:
            headers = [h.strip() for h in line.split("\t") if h.strip()]
            header_idx = i
            break

    if not headers:
        return pd.DataFrame()

    # Parse data rows (tab-separated, until a non-data line)
    size_values = {"XS", "S", "M", "L", "XL", "1X", "2X", "3X", "XXS", "XXL", "XXXL"}
    rows = []
    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if not parts:
            continue
        # Check if first column looks like a size
        if parts[0].upper() in size_values:
            row = {}
            for j, header in enumerate(headers):
                if j < len(parts):
                    row[header] = parts[j]
            rows.append(row)
        else:
            # End of size data
            break

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# LIBAS
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_libas(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Libas product page.
    Clicks "View Size Chart", toggles to cm, parses the tab-separated table.
    Handles multi-section charts (TOP + BOTTOM for suit sets).
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=HEADERS["User-Agent"])

        print(f"  Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(8000)

        # Get product title
        title = await page.evaluate("""() => {
            const el = document.querySelector('h1, .product__title, [class*="product-title"]');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Libas.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "View Size Chart"
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('*')) {
                    const t = el.textContent.trim();
                    if ((t === 'View Size Chart' || t === 'VIEW SIZE CHART')
                        && el.children.length <= 1) {
                        el.click();
                        return true;
                    }
                }
                return false;
            }""")
            if clicked:
                break
            await page.wait_for_timeout(3000)

        if not clicked:
            print("  ERROR: Could not find 'View Size Chart' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Click "cm" toggle
        await page.evaluate("""() => {
            for (const el of document.querySelectorAll('*')) {
                if (el.textContent.trim() === 'cm' && el.children.length === 0) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        await page.wait_for_timeout(2000)

        # Extract the size chart text
        text = await page.evaluate("() => document.body.innerText")
        await browser.close()

    return parse_libas_text(text, product_url, title)


def parse_libas_text(text: str, product_url: str, title: str) -> pd.DataFrame:
    """
    Parse Libas size chart from page text.

    Structure after clicking "cm" toggle:
        Body Measurement
        inch
        cm
        TOP
        Size\tXS\tS\tM\tL\tXL\tXXL
        Across Shoulder\t34.3\t35.6\t...
        Bust\t86.4\t91.4\t...
        ...
        BOTTOM
        Bottom Size\tXS\tS\tM\tL\tXL\tXXL
        Waist\t73.7\t73.7\t...
        ...
        These measurements are indicative, actual size may differ.
    """
    lines = text.split("\n")

    # Find "Body Measurement" as the anchor
    start_idx = None
    for i, line in enumerate(lines):
        if "Body Measurement" in line:
            start_idx = i
            break
    if start_idx is None:
        return pd.DataFrame()

    # Find the end marker
    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "indicative" in lines[i].lower() or "these measurement" in lines[i].lower():
            end_idx = i
            break

    # Parse sections (TOP, BOTTOM, etc.)
    all_rows = []
    current_section = ""
    sizes = []

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if not line:
            continue

        # Detect section headers
        if line in ("TOP", "BOTTOM", "DUPATTA", "KURTA", "PALAZZO",
                     "PANT", "SKIRT", "DRESS", "JACKET"):
            current_section = line
            sizes = []  # reset sizes for each section
            continue

        # Skip non-data lines
        if line in ("Body Measurement", "inch", "cm"):
            continue

        # Tab-separated data?
        if "\t" not in line:
            continue

        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 2:
            continue

        label = parts[0]
        values = parts[1:]

        # Size header row (e.g., "Size  XS  S  M  L  XL  XXL")
        if label.lower() in ("size", "bottom size"):
            sizes = values
            continue

        # Measurement row (e.g., "Bust  86.4  91.4  96.5 ...")
        if sizes:
            for j, size in enumerate(sizes):
                if j < len(values):
                    # Find or create the row for this size
                    row = None
                    for r in all_rows:
                        if r["Section"] == current_section and r["Size"] == size:
                            row = r
                            break
                    if row is None:
                        row = {"Section": current_section, "Size": size}
                        all_rows.append(row)
                    row[label] = values[j]

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_url(url: str) -> pd.DataFrame:
    """Scrape size chart from a product URL. Auto-detects the store."""
    store = detect_store(url)
    print(f"\nStore: {store.upper()}")
    print(f"URL:   {url}")

    if store == "snitch":
        return await scrape_snitch(url)
    elif store == "fashionnova":
        return await scrape_fashionnova(url)
    elif store == "libas":
        return await scrape_libas(url)
    else:
        print(f"  ERROR: Unsupported store. Supported: snitch.com, fashionnova.com, libas.in")
        return pd.DataFrame()


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    urls = sys.argv[1:]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_dfs = []

    for url in urls:
        df = await scrape_url(url)
        if df.empty:
            print("  No size chart data found.\n")
            continue

        all_dfs.append(df)

        # Print the table
        print(f"\n  Size Chart ({len(df)} sizes, all measurements in CM):\n")
        print(df.to_string(index=False))
        print()

    # Save to CSV
    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        filepath = os.path.join(OUTPUT_DIR, "size_charts.csv")
        combined.to_csv(filepath, index=False)
        print(f"Saved → {filepath}")


if __name__ == "__main__":
    asyncio.run(main())
