"""
Flask web app for the Size Chart Scraper.
Run:  python3 app.py
Open: http://localhost:8000
"""

import os
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

from scraper import scrape_url, scrape_url_static
from scraper.export import charts_to_dataframe

app = Flask(__name__)
CORS(app)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """
    POST /api/scrape
    Body: {"urls": ["url1", "url2", ...], "headless": true/false, "ocr": false}
    Returns: {"results": [...], "errors": [...]}
    """
    data = request.get_json(force=True)
    urls = data.get("urls", [])
    use_headless = data.get("headless", True)
    use_ocr = data.get("ocr", False)

    if not urls:
        return jsonify({"results": [], "errors": ["No URLs provided."]}), 400

    results = []
    errors = []
    warnings = []
    clean_urls = [u.strip() for u in urls if u.strip()]

    # Check browser service availability if headless requested
    if use_headless:
        from scraper.browser_client import browser_service_healthy
        if not browser_service_healthy():
            warnings.append("Browser service unavailable — JS-rendered stores may have incomplete data")

    for url in clean_urls:
        try:
            charts = scrape_url(url, headless=use_headless, use_ocr=use_ocr)
            data_charts = [c for c in charts if c.rows]

            if not data_charts:
                image_charts = [c for c in charts if c.image_urls]
                if image_charts:
                    results.append({
                        "url": url,
                        "product": image_charts[0].product_title,
                        "detection_method": "image_in_description",
                        "confidence": 0.4,
                        "image_urls": [img for c in image_charts for img in c.image_urls],
                        "data": [],
                        "columns": [],
                    })
                else:
                    errors.append({"url": url, "error": "No size chart data found."})
                continue

            best = max(data_charts, key=lambda c: c.confidence)
            df = charts_to_dataframe([best])
            if df.empty:
                continue

            df = df.fillna("")
            records = df.to_dict(orient="records")
            results.append({
                "url": url,
                "product": best.product_title,
                "detection_method": best.detection_method,
                "chart_type": best.chart_type,
                "unit": best.unit,
                "category": best.category,
                "confidence": best.confidence,
                "data": records,
                "columns": list(df.columns),
            })

        except Exception as e:
            errors.append({"url": url, "error": str(e)})

    response = {"results": results, "errors": errors}
    if warnings:
        response["warnings"] = warnings

    return jsonify(response)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(debug=True, host="0.0.0.0", port=port)
