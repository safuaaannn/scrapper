# Size Chart Scraper

Scrapes size chart data from any product URL. Returns structured measurements in CM.

## Quick Start

```bash
docker compose down && docker compose up --build
```

Runs on `http://localhost:8000`

## API

### Health Check

```
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "browser": "running",
  "uptime_seconds": 120,
  "max_parallel": 4
}
```

### Scrape Size Chart

```
POST /scrape
Content-Type: application/json
```

**Request:**
```json
{
  "url": "https://almostgods.com/products/zodiac-polo"
}
```

**Response (success):**
```json
{
  "success": true,
  "url": "https://almostgods.com/products/zodiac-polo",
  "store": "unknown",
  "product": "Zodiac Relaxed Polo",
  "unit": "cm",
  "columns": ["Product", "Unit", "Size", "Shoulder", "Chest", "Sleeve length", "Length"],
  "data": [
    {
      "Product": "Zodiac Relaxed Polo",
      "Unit": "cm",
      "Size": "XS",
      "Shoulder": "17.5",
      "Chest": "40",
      "Sleeve length": "9",
      "Length": "26"
    },
    {
      "Product": "Zodiac Relaxed Polo",
      "Unit": "cm",
      "Size": "S",
      "Shoulder": "18",
      "Chest": "42",
      "Sleeve length": "9.5",
      "Length": "26.5"
    }
  ],
  "error": null
}
```

**Response (failure):**
```json
{
  "success": false,
  "url": "https://example.com/products/something",
  "store": "unknown",
  "product": null,
  "unit": null,
  "columns": null,
  "data": null,
  "error": "No size chart data found"
}
```

## Scraping Layers

Requests flow through 4 layers in order. The first layer that returns data wins.

| Layer | Method | Speed | When it runs |
|-------|--------|-------|-------------|
| 0 — Regex | HTTP fetch + regex | ~0.3 sec | Store has a recipe in `scraper/recipes.py` |
| 1 — Known Store | Browser + custom scraper | ~5-15 sec | Store has a scraper in `scraper/stores/` |
| 2 — Universal | Browser + auto-detection | ~5-15 sec | Any unknown store |
| 3 — Shopify API | API call | ~1 sec | URL contains `/products/` |

## Adding a New Store (Layer 0 Recipe)

1. Open the product page in Chrome → `Ctrl+U` → copy the HTML source
2. Give the HTML to ChatGPT/Claude with this prompt:

   > I need a regex recipe to extract the size chart from this HTML. Give me these 5 fields as Python strings:
   > 1. container — regex that captures the entire size chart section
   > 2. row — regex with ONE capture group for each row inside the container
   > 3. cell — regex with ONE capture group for each cell inside a row
   > 4. value_format — one of: plain, slash_cm, slash_inches
   > 5. first_row — "headers" or "sizes"

3. Add the recipe to `scraper/recipes.py`:

   ```python
   "newstore.com": {
       "name": "New Store",
       "container": r'...',
       "row": r'...',
       "cell": r'...',
       "value_format": "plain",
       "first_row": "headers",
   },
   ```

   For Shopify stores using the **Jotly size chart app**, use:

   ```python
   "newstore.com": {
       "name": "New Store",
       "format": "jotly_json",
       "value_format": "plain",
   },
   ```

4. Rebuild and test:
   ```bash
   docker compose down && docker compose up --build -d
   curl -s -X POST http://localhost:8000/scrape \
     -H "Content-Type: application/json" \
     -d '{"url": "https://newstore.com/products/something"}' | python3 -m json.tool
   ```

## Current Recipes

| Store | Domain | Format |
|-------|--------|--------|
| Sheetal Batra | `sheetalbatra.com` | HTML regex |
| Almost Gods | `almostgods.com` | Jotly JSON |

## Known Store Scrapers (Layer 1)

Snitch, Fashion Nova, Libas, Rare Rabbit, Gymshark, Bombay Shirts, The Loom, Outdoor Voices, Good American
