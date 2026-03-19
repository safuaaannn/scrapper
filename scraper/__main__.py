"""Allow running as: python -m scraper <url1> [url2] ..."""
import asyncio
from . import main

asyncio.run(main())
