"""Snitch store scraper."""

import pandas as pd
from ..config import HEADERS, INCH_TO_CM
from ..helpers import _wait_for, _click_and_wait


async def scrape_snitch(product_url: str, browser=None) -> pd.DataFrame:
    own_browser = browser is None
    if own_browser:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)

    page = await browser.new_page(user_agent=HEADERS["User-Agent"])
    try:
        await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        await _wait_for(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if (t === 'Size Chart' || t === 'SIZE CHART') return true;
            }
            return false;
        }""", timeout=10000)

        title = await page.evaluate("""() => {
            let t = document.title || '';
            t = t.replace(/^Buy\\s+/i, '').replace(/\\s+for\\s+(men|women).*$/i, '');
            return t.trim();
        }""")
        if not title:
            title = product_url.split("/")[-2] if "/buy" in product_url else ""

        clicked = await _click_and_wait(page, """() => {
            for (const el of document.querySelectorAll('*')) {
                const t = el.textContent.trim();
                if ((t === 'Size Chart' || t === 'SIZE CHART') && el.children.length === 0) {
                    el.click(); return true;
                }
            }
            return false;
        }""", "() => document.body.innerText.includes('HOW TO MEASURE') || document.body.innerText.includes('measurements are in')", timeout=6000)
        if not clicked:
            return pd.DataFrame()

        text = await page.evaluate("() => document.body.innerText")
    finally:
        await page.close()
        if own_browser:
            await browser.close()
            await pw.stop()

    return _parse_snitch_text(text, product_url, title)


def _parse_snitch_text(text, product_url, title):
    lines = text.split("\n")
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
