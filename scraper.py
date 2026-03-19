"""
Size Chart Scraper — Snitch, Fashion Nova, Libas, Rare Rabbit, Gymshark, Bombay Shirts, The Loom, Outdoor Voices & Good American
Give it a product URL → get the size chart in CM as CSV.

Usage:
    python3 scraper.py <product_url>
    python3 scraper.py <url1> <url2> <url3> ...

Examples:
    python3 scraper.py "https://www.snitch.com/men-shirts/lining-maroon-shirt/7355129528482/buy"
    python3 scraper.py "https://www.fashionnova.com/products/carina-snatched-pant-set-black"
    python3 scraper.py "https://www.libas.in/products/peach-self-design-silk-blend-straight-suit-set-33549o"
    python3 scraper.py "https://thehouseofrare.com/products/some-product"
    python3 scraper.py "https://row.gymshark.com/products/some-product"
    python3 scraper.py "https://www.bombayshirts.com/products/some-product"

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
    if "thehouseofrare.com" in host:
        return "rarerabbit"
    if "gymshark.com" in host:
        return "gymshark"
    if "bombayshirts.com" in host:
        return "bombayshirts"
    if "theloom.in" in host:
        return "theloom"
    if "outdoorvoices.com" in host:
        return "outdoorvoices"
    if "goodamerican.com" in host:
        return "goodamerican"
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
# RARE RABBIT
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_rarerabbit(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Rare Rabbit (thehouseofrare.com) product page.
    Uses Kiwi Sizing app — HTML tables with ks-table-* classes.
    Data is already in CM by default.
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
            t = t.replace(/\\s*[|–-]\\s*Rare Rabbit.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "SIZE GUIDE" button
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('*')) {
                    const t = el.textContent.trim().toUpperCase();
                    if ((t === 'SIZE GUIDE' || t === 'SIZE CHART')
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
            print("  ERROR: Could not find 'SIZE GUIDE' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Extract data from Kiwi Sizing HTML table
        table_data = await page.evaluate("""() => {
            // Look for Kiwi Sizing tables (ks-table-* classes)
            let table = document.querySelector('table[class*="ks-table"], .kiwi-sizing table, table.ks-table');
            // Fallback: any visible table in a modal/popup
            if (!table) {
                const tables = document.querySelectorAll('table');
                for (const t of tables) {
                    if (t.offsetParent !== null && t.rows.length > 1) {
                        table = t;
                        break;
                    }
                }
            }
            if (!table) return null;

            const rows = [];
            for (const tr of table.rows) {
                const cells = [];
                for (const td of tr.cells) {
                    cells.push(td.textContent.trim());
                }
                rows.push(cells);
            }
            return rows;
        }""")

        await browser.close()

    if not table_data or len(table_data) < 2:
        print("  ERROR: No size chart table found")
        return pd.DataFrame()

    # First row is headers
    headers = table_data[0]
    rows = []
    for row_data in table_data[1:]:
        if not any(cell.strip() for cell in row_data):
            continue
        row = {}
        for j, header in enumerate(headers):
            if j < len(row_data):
                row[header] = row_data[j]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# GYMSHARK
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_gymshark(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Gymshark product page.
    Clicks "Size Guide" button, extracts data from HTML table.
    Data is already in CM.
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
            const el = document.querySelector('h1, [data-locator-id*="product-title"]');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Gymshark.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "Size Guide" — target button specifically (DIV wrapper doesn't trigger modal)
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                // Try specific class first
                const btn = document.querySelector('button[class*="size-guide"]');
                if (btn) { btn.click(); return true; }
                // Fallback: any button with "Size Guide" text
                for (const el of document.querySelectorAll('button')) {
                    if (el.textContent.trim() === 'Size Guide') {
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
            print("  ERROR: Could not find 'Size Guide' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Extract data from HTML table (Gymshark renders size data as <table>)
        table_data = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) return rows;
            }
            return null;
        }""")

        await browser.close()

    if not table_data or len(table_data) < 2:
        print("  ERROR: No size chart table found")
        return pd.DataFrame()

    # First row is headers
    headers = table_data[0]
    rows = []
    for row_data in table_data[1:]:
        if not any(cell.strip() for cell in row_data):
            continue
        row = {}
        for j, header in enumerate(headers):
            if j < len(row_data):
                row[header.capitalize()] = row_data[j]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# BOMBAY SHIRTS
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_bombayshirts(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Bombay Shirts product page.
    Clicks "Size Guide", extracts CM table data.
    Tables come in inch/cm pairs — we grab the CM version.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent=HEADERS["User-Agent"])

        print(f"  Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Get product title from document.title (h1 is a support widget)
        title = await page.evaluate("""() => {
            let t = document.title || '';
            t = t.replace(/\\s*[–—|\\-]\\s*Bombay Shirt.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "Size Guide"
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('*')) {
                    const t = el.textContent.trim();
                    if ((t === 'Size Guide' || t === 'SIZE GUIDE' || t === 'Size guide')
                        && el.children.length <= 2) {
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
            print("  ERROR: Could not find 'Size Guide' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Extract ALL tables (including hidden ones — we need the CM table)
        # Tables come in pairs: inch table, then cm table
        # The overview table with "Size" header has all measurements
        all_tables = await page.evaluate("""() => {
            const results = [];
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) {
                        cells.push(td.textContent.trim());
                    }
                    rows.push(cells);
                }
                if (rows.length > 1) {
                    results.push(rows);
                }
            }
            return results;
        }""")

        await browser.close()

    if not all_tables:
        print("  ERROR: No size chart tables found")
        return pd.DataFrame()

    # Find the CM overview table: has "Size" in first header cell + cm-scale values
    # Prefer the table with the most columns (most measurements)
    candidates = []
    for table in all_tables:
        headers = table[0]
        if not headers or "Size" not in headers[0]:
            continue
        # Check if values are in cm range (chest > 50 means cm)
        is_cm = False
        for row in table[1:]:
            for val in row[1:]:
                try:
                    if float(val) > 50:
                        is_cm = True
                        break
                except ValueError:
                    continue
            if is_cm:
                break
        if is_cm:
            candidates.append(table)

    # Pick the best candidate: most columns first, then largest values (cm > inches)
    best_table = None
    if candidates:
        def table_score(t):
            num_cols = len(t[0])
            # Sum all numeric values — cm table will have much higher sum
            total = 0
            for row in t[1:]:
                for val in row[1:]:
                    try:
                        total += float(val)
                    except ValueError:
                        pass
            return (num_cols, total)
        best_table = max(candidates, key=table_score)

    if not best_table or len(best_table) < 2:
        print("  ERROR: Could not find CM size chart table")
        return pd.DataFrame()

    # Parse the table
    headers = best_table[0]
    rows = []
    for row_data in best_table[1:]:
        if not any(cell.strip() for cell in row_data):
            continue
        row = {}
        for j, header in enumerate(headers):
            if j < len(row_data):
                row[header] = row_data[j]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# THE LOOM
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_theloom(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a The Loom product page.
    Clicks "Size Chart", toggles to "Cm", extracts HTML table.
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
            let t = document.title || '';
            t = t.replace(/^Buy\\s+/i, '').replace(/\\s*[|].*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.rstrip("/").split("/")[-1].replace("-", " ").title()

        # Click "Size Chart"
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('b, span, a, button, div')) {
                    const t = el.textContent.trim();
                    if ((t === 'Size Chart' || t === 'SIZE CHART') && el.children.length <= 1) {
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
            print("  ERROR: Could not find 'Size Chart' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Click "Cm" toggle
        await page.evaluate("""() => {
            for (const el of document.querySelectorAll('button, span, div')) {
                const t = el.textContent.trim();
                if ((t === 'Cm' || t === 'CM' || t === 'cm') && el.children.length === 0) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        await page.wait_for_timeout(2000)

        # Extract HTML table + page text (for dupatta info)
        table_data = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) return rows;
            }
            return null;
        }""")

        page_text = await page.evaluate("() => document.body.innerText")
        await browser.close()

    # Parse dupatta info from text (e.g., "Dupatta: Length- 2.5 mtr, Width- 36"")
    dupatta_info = {}
    if page_text:
        for line in page_text.split("\n"):
            if "dupatta" in line.lower() and ("length" in line.lower() or "width" in line.lower()):
                # Parse "Dupatta: Length- 2.5 mtr, Width- 36""
                length_match = re.search(r'Length[-:\s]*([\d.]+)\s*(mtr|m|cm)', line, re.IGNORECASE)
                width_match = re.search(r'Width[-:\s]*([\d.]+)\s*["\u201d]?', line, re.IGNORECASE)
                if length_match:
                    val = float(length_match.group(1))
                    unit = length_match.group(2).lower()
                    # Convert to cm
                    if unit in ("mtr", "m"):
                        dupatta_info["Dupatta Length"] = round(val * 100, 1)
                    else:
                        dupatta_info["Dupatta Length"] = val
                if width_match:
                    val = float(width_match.group(1))
                    # Assume inches if no unit or has " symbol
                    dupatta_info["Dupatta Width"] = round(val * INCH_TO_CM, 1)
                break

    if not table_data or len(table_data) < 2:
        print("  ERROR: No size chart table found")
        return pd.DataFrame()

    # Parse multi-section table:
    #   Row: ['Kurta', '', '', ...]         <- section header
    #   Row: ['', 'XXS', 'XS', 'S', ...]   <- sizes row
    #   Row: ['Chest', '76', '81', ...]     <- measurement
    #   ...
    #   Row: ['', '', '', ...]              <- empty separator
    #   Row: ['Pants', '', '', ...]         <- next section
    #   Row: ['', 'XXS', 'XS', ...]        <- sizes row again
    #   ...
    all_rows = []
    current_section = ""
    sizes = []

    for table_row in table_data:
        non_empty = [c for c in table_row if c.strip()]

        # Empty row — separator
        if not non_empty:
            continue

        # Section header: only first cell has text, rest empty
        if len(non_empty) == 1 and not table_row[0].replace(" ", "").isdigit():
            first = table_row[0].strip()
            # Check it's a label (not a measurement value)
            if first and not any(c.isdigit() for c in first):
                current_section = first
                sizes = []
                continue

        # Sizes row: first cell empty, rest are size labels
        if not table_row[0].strip() and len(non_empty) >= 2:
            candidate_sizes = [c.strip() for c in table_row[1:] if c.strip()]
            if candidate_sizes:
                sizes = candidate_sizes
                continue

        # Measurement row: first cell is label, rest are values
        measure_name = table_row[0].strip()
        if measure_name and sizes:
            values = table_row[1:]
            for i, size in enumerate(sizes):
                if i < len(values) and values[i].strip():
                    # Find or create the row for this section+size
                    row = None
                    for r in all_rows:
                        if r.get("Section") == current_section and r["Size"] == size:
                            row = r
                            break
                    if row is None:
                        row = {"Section": current_section, "Size": size}
                        all_rows.append(row)
                    row[measure_name] = values[i].strip()

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    # If only one section, drop the Section column
    if df["Section"].nunique() <= 1:
        df = df.drop(columns=["Section"])

    # Add dupatta info if found (same value for all rows)
    if dupatta_info:
        for col, val in dupatta_info.items():
            df[col] = val

    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


# ═══════════════════════════════════════════════════════════════════════════
# OUTDOOR VOICES
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_outdoorvoices(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from an Outdoor Voices product page.
    Clicks "Size Guide" button, extracts "Find Your Fit" table.
    Values are inch ranges — converted to cm by averaging.
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
            const el = document.querySelector('h1');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Outdoor Voices.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "Size Guide"
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('button, a, span')) {
                    const t = el.textContent.trim();
                    if (t === 'Size Guide') {
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
            print("  ERROR: Could not find 'Size Guide' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(3000)

        # Extract table
        table_data = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) return rows;
            }
            return null;
        }""")

        await browser.close()

    if not table_data or len(table_data) < 2:
        print("  ERROR: No size chart table found")
        return pd.DataFrame()

    # Table format: ['', 'XS', 'S', 'M', 'L', 'XL']
    #               ['Chest', '31 – 33"', '33 – 35"', ...]
    sizes = table_data[0][1:]
    rows = []

    for i, size in enumerate(sizes):
        if not size.strip():
            continue
        row = {"Size": size}
        for data_row in table_data[1:]:
            if len(data_row) < 2:
                continue
            measure_name = data_row[0]
            if not measure_name.strip():
                continue
            if i + 1 < len(data_row):
                val = data_row[i + 1]
                row[measure_name] = _inch_range_to_cm(val)
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


def _inch_range_to_cm(val: str):
    """
    Convert inch range like '31 – 33"' or '33 1/2 – 35 1/2"' to cm.
    Returns averaged cm value, or original string if not parseable.
    """
    val = val.replace('\xa0', ' ').replace('"', '').replace('"', '').strip()

    # Handle fractions like "33 1/2"
    def parse_fraction(s):
        s = s.strip()
        match = re.match(r'(\d+)\s+(\d+)/(\d+)', s)
        if match:
            return int(match.group(1)) + int(match.group(2)) / int(match.group(3))
        try:
            return float(s)
        except ValueError:
            return None

    # Try range: "31 – 33" or "33 1/2 – 35 1/2"
    parts = re.split(r'\s*[–-]\s*', val)
    if len(parts) == 2:
        low = parse_fraction(parts[0])
        high = parse_fraction(parts[1])
        if low is not None and high is not None:
            avg = (low + high) / 2
            return round(avg * INCH_TO_CM, 1)

    # Try single number
    num = parse_fraction(val)
    if num is not None:
        return round(num * INCH_TO_CM, 1)

    return val


# ═══════════════════════════════════════════════════════════════════════════
# GOOD AMERICAN
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_goodamerican(product_url: str) -> pd.DataFrame:
    """
    Scrape size chart from a Good American product page.
    Clicks "Size Guide" button, clicks "CM" toggle, extracts table.
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
            const el = document.querySelector('h1');
            if (el) return el.textContent.trim();
            let t = document.title || '';
            t = t.replace(/\\s*[|–-]\\s*Good American.*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/products/")[-1].replace("-", " ").title()

        # Click "Size Guide"
        clicked = False
        for attempt in range(3):
            clicked = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('button')) {
                    if (el.textContent.trim() === 'Size Guide') {
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
            print("  ERROR: Could not find 'Size Guide' button")
            await browser.close()
            return pd.DataFrame()

        await page.wait_for_timeout(5000)

        # Click "CM" toggle
        await page.evaluate("""() => {
            for (const el of document.querySelectorAll('button, span, div')) {
                const t = el.textContent.trim();
                if ((t === 'CM' || t === 'Cm' || t === 'cm') && el.children.length === 0) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""")
        await page.wait_for_timeout(3000)

        # Extract table
        table_data = await page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            for (const table of tables) {
                if (table.offsetParent === null) continue;
                const rows = [];
                for (const tr of table.rows) {
                    const cells = [];
                    for (const td of tr.cells) cells.push(td.textContent.trim());
                    rows.push(cells);
                }
                if (rows.length > 1) return rows;
            }
            return null;
        }""")

        await browser.close()

    if not table_data or len(table_data) < 2:
        print("  ERROR: No size chart table found")
        return pd.DataFrame()

    # Standard table: ['Size', 'Waist', 'Hip', 'Inseam'] then data rows
    headers = table_data[0]
    rows = []
    for row_data in table_data[1:]:
        if not any(cell.strip() for cell in row_data):
            continue
        row = {}
        for j, header in enumerate(headers):
            if j < len(row_data):
                row[header] = row_data[j]
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
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

    scrapers = {
        "snitch": scrape_snitch,
        "fashionnova": scrape_fashionnova,
        "libas": scrape_libas,
        "rarerabbit": scrape_rarerabbit,
        "gymshark": scrape_gymshark,
        "bombayshirts": scrape_bombayshirts,
        "theloom": scrape_theloom,
        "outdoorvoices": scrape_outdoorvoices,
        "goodamerican": scrape_goodamerican,
    }

    if store in scrapers:
        return await scrapers[store](url)
    else:
        supported = ", ".join(scrapers.keys())
        print(f"  ERROR: Unsupported store. Supported: {supported}")
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
