"""Snitch store scraper.

Snitch is a Shopify + Next.js site. The size chart data is fetched from
an internal API when the "Size Chart" modal opens. We intercept that API
response for reliable structured data, with DOM text parsing as fallback.
"""

import json
import pandas as pd
from ..config import INCH_TO_CM
from ..helpers import _wait_for, launch_browser, create_stealth_context


async def scrape_snitch(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    pw = None
    if own_browser:
        pw, browser = await launch_browser()

    ctx = await create_stealth_context(browser, locale="en-IN")
    page = await ctx.new_page()

    # Capture size-chart API responses
    api_data = []

    async def on_response(response):
        try:
            if "size-chart" in response.url and response.status == 200:
                body = await response.json()
                api_data.append(body)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        print(f"  [snitch] Loading page...")
        await page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        print(f"  [snitch] Page: {await page.title()}")

        # Extract product title
        title = await page.evaluate("""() => {
            let t = document.title || '';
            t = t.replace(/^Buy\\s+/i, '').replace(/\\s+for\\s+(men|women).*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/")[-2] if "/buy" in product_url else ""

        # Click "Size Chart" to open the modal (triggers API call)
        # Use expect_response to catch the size-chart API call
        clicked = False
        try:
            async with page.expect_response(
                lambda r: "size-chart" in r.url and r.status == 200,
                timeout=10000,
            ) as response_info:
                for label in ["Size Chart", "SIZE CHART", "size chart"]:
                    try:
                        locator = page.get_by_text(label, exact=True).first
                        if await locator.is_visible(timeout=2000):
                            await locator.click(timeout=5000)
                            print(f"  [snitch] Clicked '{label}'")
                            clicked = True
                            break
                    except Exception:
                        continue

            if clicked:
                try:
                    resp = await response_info.value
                    api_json = await resp.json()
                    api_data.append(api_json)
                    print(f"  [snitch] Intercepted API: {resp.url}")
                except Exception:
                    pass
        except Exception:
            # API response not caught — modal might still have opened
            if not clicked:
                for label in ["Size Chart", "SIZE CHART", "size chart"]:
                    try:
                        locator = page.get_by_text(label, exact=True).first
                        if await locator.is_visible(timeout=2000):
                            await locator.click(timeout=5000)
                            print(f"  [snitch] Clicked '{label}' (no API)")
                            clicked = True
                            break
                    except Exception:
                        continue

        if not clicked:
            print(f"  [snitch] Could not find/click Size Chart trigger")
            return pd.DataFrame()

        # Wait for modal content to fully render
        await _wait_for(page, """() => {
            for (const el of document.querySelectorAll('div')) {
                const style = getComputedStyle(el);
                const z = parseInt(style.zIndex);
                if (z > 1000 && style.visibility === 'visible') {
                    const t = el.innerText || '';
                    if (t.includes('SIZE') && (t.includes('WAIST') || t.includes('CHEST') ||
                        t.includes('HIP') || t.includes('LENGTH')))
                        return true;
                }
            }
            return false;
        }""", timeout=8000)

        # Strategy 1: Extract text from the modal (shows product-specific sizes)
        print(f"  [snitch] Extracting modal text...")
        modal_text = await page.evaluate("""() => {
            for (const el of document.querySelectorAll('div')) {
                const style = getComputedStyle(el);
                const zIndex = parseInt(style.zIndex);
                if (zIndex > 1000 && style.visibility === 'visible') {
                    return el.innerText;
                }
            }
            return null;
        }""")

        if modal_text:
            print(f"  [snitch] Got modal text ({len(modal_text)} chars)")
            df = _parse_snitch_text(modal_text, product_url, title)
            if not df.empty:
                return df

        # Strategy 2: Use API data with fit filtering
        if api_data:
            # Extract product fit from page text (e.g., "Fit - Baggy Fit")
            fit_name = await page.evaluate("""() => {
                const text = document.body.innerText;
                const match = text.match(/Fit\\s*[-–:]\\s*([A-Za-z ]+?)\\s*(?:Fit)?\\s*\\n/i);
                return match ? match[1].trim() : '';
            }""")
            print(f"  [snitch] Trying API data (fit: {fit_name or 'unknown'})...")
            df = _parse_api_data(api_data[0], title, fit_name)
            if not df.empty:
                print(f"  [snitch] API parse: {len(df)} sizes")
                return df

        # Strategy 3: Fall back to body.innerText
        print(f"  [snitch] Trying body.innerText...")
        text = await page.evaluate("() => document.body.innerText")
        return _parse_snitch_text(text, product_url, title)

    finally:
        await page.close()
        await ctx.close()
        if own_browser:
            await browser.close()
            if pw:
                await pw.stop()


def _parse_api_data(api_response, title, fit_name=""):
    """Parse the structured JSON from Snitch's size-chart API."""
    data = api_response.get("data", [])
    if not data:
        return pd.DataFrame()

    # Filter by fit if specified and data has fit field
    if fit_name and any("fit" in item for item in data):
        fit_lower = fit_name.lower()
        filtered = [item for item in data if fit_lower in item.get("fit", "").lower()]
        if filtered:
            data = filtered

    rows = []
    for item in data:
        row = {"Size": item.get("size", "")}
        for key, val in item.items():
            if key in ("size", "fit"):
                continue
            if isinstance(val, (int, float)):
                # API returns inches — convert to cm
                row[key.upper()] = round(val * INCH_TO_CM, 1)
            else:
                row[key.upper()] = val
        rows.append(row)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Capitalize column names nicely
    df.columns = [c.capitalize() if c != "Size" else c for c in df.columns]
    df.insert(0, "Product", title)
    df.insert(1, "Unit", "cm")
    return df


def _parse_snitch_text(text, product_url, title):
    """Parse size chart from text (modal innerText or body.innerText)."""
    lines = text.split("\n")
    start_idx = None

    # Find the start of chart data (after "HOW TO MEASURE" header or before "measurements are in")
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

    end_idx = len(lines)
    for i in range(start_idx, len(lines)):
        if "measurements are in" in lines[i].lower():
            end_idx = i
            break

    unit = "inches"
    if end_idx < len(lines) and "cm" in lines[end_idx].lower():
        unit = "cm"

    chart_lines = [lines[i].strip() for i in range(start_idx, end_idx) if lines[i].strip()]
    measurement_keywords = {
        "CHEST", "LENGTH", "SHOULDER", "SLEEVE", "WAIST", "HIP",
        "HIPS", "INSEAM", "BUST", "THIGH", "NECK", "OUTSEAM",
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
