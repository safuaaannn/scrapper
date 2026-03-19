"""
Flask web app for the Size Chart Scraper.
Run:  python3 app.py
Open: http://localhost:5000
"""

import asyncio
import os
import json
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Import from the scraper package
from scraper import scrape_url

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """
    POST /api/scrape
    Body: {"urls": ["url1", "url2", ...]}
    Returns: {"results": [...], "errors": [...]}
    """
    data = request.get_json(force=True)
    urls = data.get("urls", [])

    if not urls:
        return jsonify({"results": [], "errors": ["No URLs provided."]}), 400

    results = []
    errors = []

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run_all():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            clean_urls = [u.strip() for u in urls if u.strip()]
            task_results = await asyncio.gather(
                *[scrape_url(u, browser=browser) for u in clean_urls],
                return_exceptions=True,
            )
            await browser.close()
            return list(zip(clean_urls, task_results))

    try:
        url_results = loop.run_until_complete(run_all())
        for url, result in url_results:
            if isinstance(result, Exception):
                errors.append({"url": url, "error": str(result)})
            elif result.empty:
                errors.append({"url": url, "error": "No size chart data found."})
            else:
                df = result.fillna("")
                records = df.to_dict(orient="records")
                results.append({
                    "url": url,
                    "product": records[0].get("Product", "") if records else "",
                    "data": records,
                    "columns": list(df.columns),
                })
    except Exception as e:
        errors.append({"url": "all", "error": str(e)})
    finally:
        loop.close()

    return jsonify({"results": results, "errors": errors})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
