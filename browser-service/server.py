"""
Browser microservice — REST API wrapping Playwright scrapers.

Endpoints:
  POST /scrape   — scrape a URL using headless Chromium
  GET  /health   — pool status and health check
"""

import os
import time
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

from browser_pool import BrowserPool
from scraper import detect_store
from scraper.stores import STORE_SCRAPERS
from scraper.universal.pipeline import scrape_universal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pool = BrowserPool()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Browser service starting...")
    yield
    logger.info("Browser service shutting down...")
    await pool.shutdown()


app = FastAPI(title="Browser Scraper Service", lifespan=lifespan)


# ── Request / Response models ─────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str
    store: str = ""
    timeout_ms: int = 60000
    use_ocr: bool = False


class MeasurementRowResponse(BaseModel):
    size: str
    measurements: dict


class ScrapeResponse(BaseModel):
    success: bool
    product_title: str = ""
    unit: str = "cm"
    headers: list = []
    rows: list[MeasurementRowResponse] = []
    confidence: float = 0.0
    detection_method: str = ""
    image_urls: list = []
    error: str = ""
    duration_ms: int = 0


# ── Helpers ────────────────────────────────────────────────────────

def _df_to_response(df: pd.DataFrame, detection_method: str,
                    start_time: float, confidence: float = 0.7) -> ScrapeResponse:
    """Convert a legacy DataFrame result to ScrapeResponse."""
    if df.empty:
        return ScrapeResponse(
            success=False,
            error="Scraper returned empty DataFrame",
            duration_ms=int((time.time() - start_time) * 1000),
        )

    product_title = df["Product"].iloc[0] if "Product" in df.columns else ""
    unit = df["Unit"].iloc[0] if "Unit" in df.columns else "cm"

    # Check for image-only results
    if "_image_urls" in df.columns:
        image_urls = df["_image_urls"].iloc[0].split(",")
        return ScrapeResponse(
            success=True,
            product_title=product_title,
            detection_method=detection_method,
            image_urls=image_urls,
            confidence=0.4,
            duration_ms=int((time.time() - start_time) * 1000),
        )

    skip = {"Product", "Unit", "Size"}
    measurement_cols = [c for c in df.columns if c not in skip]
    headers = ["Size"] + measurement_cols

    rows = []
    size_col = "Size" if "Size" in df.columns else None
    if size_col is None:
        for c in df.columns:
            if "size" in c.lower():
                size_col = c
                break

    if size_col:
        for _, row in df.iterrows():
            measurements = {}
            for col in measurement_cols:
                val = str(row.get(col, "")).strip()
                if val and val != "nan":
                    measurements[col] = val
            if measurements:
                rows.append(MeasurementRowResponse(
                    size=str(row[size_col]).strip(),
                    measurements=measurements,
                ))

    return ScrapeResponse(
        success=bool(rows),
        product_title=product_title,
        unit=unit,
        headers=headers,
        rows=rows,
        confidence=confidence,
        detection_method=detection_method,
        duration_ms=int((time.time() - start_time) * 1000),
    )


# ── Endpoints ──────────────────────────────────────────────────────

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest):
    """Scrape a URL using headless Chromium."""
    start = time.time()

    # Detect store if not provided
    store = req.store or detect_store(req.url)

    instance = await pool.acquire()
    try:
        browser = instance.browser

        # Try store-specific scraper first
        if store and store in STORE_SCRAPERS:
            logger.info(f"Using {store} scraper for {req.url}")
            try:
                df = await STORE_SCRAPERS[store](req.url, browser=browser)
                if not df.empty:
                    return _df_to_response(df, f"{store}_scraper", start)
                logger.info(f"{store} scraper returned empty, trying universal")
            except Exception as e:
                logger.warning(f"{store} scraper failed: {e}, trying universal")

        # Fall back to universal scraper
        logger.info(f"Using universal scraper for {req.url}")
        df, confidence = await scrape_universal(
            req.url, browser=browser, use_ocr=req.use_ocr
        )

        if not df.empty:
            return _df_to_response(df, "universal", start, confidence)

        return ScrapeResponse(
            success=False,
            error="No size chart found",
            duration_ms=int((time.time() - start) * 1000),
        )

    except Exception as e:
        logger.error(f"Scrape failed for {req.url}: {e}")
        return ScrapeResponse(
            success=False,
            error=str(e),
            duration_ms=int((time.time() - start) * 1000),
        )
    finally:
        await pool.release(instance)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "pool": pool.status()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
