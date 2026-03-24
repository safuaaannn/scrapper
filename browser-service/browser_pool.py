"""
Browser pool — manages Chromium instances for the browser microservice.

Features:
  - Reusable browser instances (avoid cold-start per request)
  - Auto-recycle after N requests (prevents memory leaks)
  - Concurrency control via semaphore
  - Health status reporting
"""

import asyncio
import os
import logging

logger = logging.getLogger(__name__)

MAX_BROWSERS = int(os.getenv("MAX_BROWSERS", "2"))
RECYCLE_AFTER = int(os.getenv("RECYCLE_AFTER", "100"))


class BrowserInstance:
    """Wraps a single Playwright browser with usage tracking."""

    def __init__(self, browser, pw_context):
        self.browser = browser
        self.pw_context = pw_context
        self.request_count = 0
        self.in_use = False

    @property
    def needs_recycle(self):
        return self.request_count >= RECYCLE_AFTER

    async def close(self):
        try:
            await self.browser.close()
        except Exception:
            pass
        try:
            await self.pw_context.stop()
        except Exception:
            pass


class BrowserPool:
    """Pool of headless Chromium browsers."""

    def __init__(self):
        self._instances: list[BrowserInstance] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(MAX_BROWSERS)
        self._started = False

    async def _create_instance(self) -> BrowserInstance:
        """Launch a new Chromium browser."""
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        instance = BrowserInstance(browser, pw)
        logger.info(f"Created new browser instance (total: {len(self._instances) + 1})")
        return instance

    async def acquire(self):
        """Acquire a browser from the pool. Blocks if all are in use."""
        await self._semaphore.acquire()

        async with self._lock:
            # Find a free instance that doesn't need recycling
            for inst in self._instances:
                if not inst.in_use and not inst.needs_recycle:
                    inst.in_use = True
                    inst.request_count += 1
                    return inst

            # Recycle any stale instances
            for inst in list(self._instances):
                if inst.needs_recycle and not inst.in_use:
                    logger.info(f"Recycling browser after {inst.request_count} requests")
                    await inst.close()
                    self._instances.remove(inst)

            # Create new instance if under limit
            if len(self._instances) < MAX_BROWSERS:
                inst = await self._create_instance()
                inst.in_use = True
                inst.request_count = 1
                self._instances.append(inst)
                return inst

        # All instances busy and at limit — wait for one to free up
        # (semaphore already handles this, but just in case)
        self._semaphore.release()
        await asyncio.sleep(0.5)
        return await self.acquire()

    async def release(self, instance: BrowserInstance):
        """Release a browser back to the pool."""
        instance.in_use = False
        self._semaphore.release()

    async def shutdown(self):
        """Close all browser instances."""
        async with self._lock:
            for inst in self._instances:
                await inst.close()
            self._instances.clear()
        logger.info("Browser pool shut down")

    def status(self) -> dict:
        """Health status of the pool."""
        return {
            "total_browsers": len(self._instances),
            "max_browsers": MAX_BROWSERS,
            "in_use": sum(1 for i in self._instances if i.in_use),
            "available": sum(1 for i in self._instances if not i.in_use),
            "recycle_after": RECYCLE_AFTER,
            "request_counts": [i.request_count for i in self._instances],
        }
