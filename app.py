"""
Size Chart Scraper — Production Microservice.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

from scraper import scrape_url, detect_store
from scraper.config import BROWSER_ARGS, MAX_PARALLEL
from scraper.helpers import launch_browser

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("scraper-service")

# ---------------------------------------------------------------------------
# Browser pool — single Chromium instance reused across all requests
# ---------------------------------------------------------------------------
SCRAPE_TIMEOUT = 60  # seconds per scrape
_browser = None
_pw = None
_start_time: float = 0
_semaphore: asyncio.Semaphore | None = None


async def _start_browser():
    global _browser, _pw, _start_time, _semaphore
    _pw, _browser = await launch_browser()
    _start_time = time.time()
    _semaphore = asyncio.Semaphore(MAX_PARALLEL)
    log.info("Browser started (max %d parallel scrapes)", MAX_PARALLEL)


async def _stop_browser():
    global _browser, _pw
    if _browser:
        await _browser.close()
        _browser = None
    if _pw:
        await _pw.stop()
        _pw = None
    log.info("Browser stopped")


async def _get_browser():
    """Return the shared browser, restarting if it crashed."""
    global _browser
    if _browser is None or not _browser.is_connected():
        log.warning("Browser not connected — restarting...")
        await _stop_browser()
        await _start_browser()
    return _browser


# ---------------------------------------------------------------------------
# FastAPI lifespan — start/stop browser with the server
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await _start_browser()
    yield
    await _stop_browser()


app = FastAPI(
    title="Size Chart Scraper",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ScrapeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("Invalid URL — must start with http:// or https://")
        return v


class ScrapeResult(BaseModel):
    success: bool
    url: str
    store: str
    product: str | None = None
    unit: str | None = None
    columns: list[str] | None = None
    data: list[dict] | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    browser: str
    uptime_seconds: int
    max_parallel: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health():
    browser_status = "running" if _browser and _browser.is_connected() else "down"
    return HealthResponse(
        status="ok" if browser_status == "running" else "degraded",
        browser=browser_status,
        uptime_seconds=int(time.time() - _start_time) if _start_time else 0,
        max_parallel=MAX_PARALLEL,
    )


@app.post("/scrape", response_model=ScrapeResult)
async def scrape(req: ScrapeRequest):
    store = detect_store(req.url)
    browser = await _get_browser()

    async with _semaphore:
        try:
            df = await asyncio.wait_for(
                scrape_url(req.url, browser=browser),
                timeout=SCRAPE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.error("Scrape timed out after %ds: %s", SCRAPE_TIMEOUT, req.url)
            return ScrapeResult(
                success=False,
                url=req.url,
                store=store,
                error=f"Scrape timed out after {SCRAPE_TIMEOUT}s",
            )
        except Exception as e:
            log.exception("Scrape failed: %s", req.url)
            return ScrapeResult(
                success=False,
                url=req.url,
                store=store,
                error=str(e),
            )

    if df.empty:
        return ScrapeResult(
            success=False,
            url=req.url,
            store=store,
            error="No size chart data found",
        )

    df = df.fillna("")
    records = df.to_dict(orient="records")
    return ScrapeResult(
        success=True,
        url=req.url,
        store=store,
        product=records[0].get("Product", "") if records else None,
        unit="cm",
        columns=list(df.columns),
        data=records,
    )
