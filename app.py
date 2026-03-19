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

# Import scraper functions
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

    try:
        for url in urls:
            url = url.strip()
            if not url:
                continue
            try:
                df = loop.run_until_complete(scrape_url(url))
                if df.empty:
                    errors.append({"url": url, "error": "No size chart data found."})
                else:
                    # Convert DataFrame to list of dicts (replace NaN with None for valid JSON)
                    df = df.fillna("")
                    records = df.to_dict(orient="records")
                    results.append({
                        "url": url,
                        "product": records[0].get("Product", "") if records else "",
                        "data": records,
                        "columns": list(df.columns),
                    })
            except Exception as e:
                errors.append({"url": url, "error": str(e)})
    finally:
        loop.close()

    return jsonify({"results": results, "errors": errors})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
