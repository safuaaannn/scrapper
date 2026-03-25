"""
Store recipes for regex-based scraping (Layer 0 — no browser needed).

Each recipe tells the regex engine how to find and extract size chart data
from a store's raw HTML source. This is 30x faster than browser scraping.

HOW TO ADD A NEW STORE:
  1. Open a product page in Chrome → press Ctrl+U to view source
  2. Copy the entire HTML and give it to ChatGPT/Claude with this prompt:

     "I need a regex recipe to extract the size chart from this HTML.
      Give me these 5 fields as Python strings:
      1. container — regex that captures the entire size chart section
      2. row       — regex with ONE capture group for each row inside the container
      3. cell      — regex with ONE capture group for each cell inside a row
      4. value_format — one of: plain, slash_cm, slash_inches
         plain         = values like '96' or '76.2' (use as-is)
         slash_cm      = values like '30/76.2' (take the part after /)
         slash_inches  = values like '76.2/30' (take the part before /)
      5. first_row — 'headers' if first row is column names (Size, Chest, Waist)
                      'sizes' if first row is size labels (S, M, L, XL)"

  3. Paste the recipe below using the store's domain as the key.
  4. Test it: curl -X POST http://localhost:8000/scrape -d '{"url": "..."}'
"""

RECIPES = {

    # ── Sheetal Batra ──────────────────────────────────────────────────
    # Layout: <ul class="main-size"> lists, each list is one measurement row.
    # First list = size labels, rest = measurements.
    # Values: "30/76.2" (inches/cm) → take cm part.
    "sheetalbatra.com": {
        "name": "Sheetal Batra",
        "container": r'<ul class="main-chrt"[^>]*>(.*?)</ul>\s*</li>\s*</ul>',
        "row": r'<ul[^>]*class="main-size[^"]*"[^>]*>(.*?)</ul>',
        "cell": r'<li>(.*?)</li>',
        "value_format": "slash_cm",
        "first_row": "sizes",
    },

    # ── Example: standard HTML table store ─────────────────────────────
    # Uncomment and fill in when you onboard a table-based store.
    #
    # "example-store.com": {
    #     "name": "Example Store",
    #     "container": r'<table[^>]*class="size-chart"[^>]*>(.*?)</table>',
    #     "row": r'<tr[^>]*>(.*?)</tr>',
    #     "cell": r'<t[dh][^>]*>(.*?)</t[dh]>',
    #     "value_format": "plain",
    #     "first_row": "headers",
    # },
    # ── Almost Gods ────────────────────────────────────────────────────
    # Uses Jotly size chart app — data is embedded as JSON in the HTML.
    # Format "jotly_json" tells the engine to parse JSON instead of regex.
    # measurementUnit is "inch" but targetUnit is "cm", values are in inches.
    "almostgods.com": {
        "name": "Almost Gods",
        "format": "jotly_json",
        "value_format": "plain",
    },

}
