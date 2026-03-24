"""Browser service scraper — store detection and routing."""

from urllib.parse import urlparse


def detect_store(url: str) -> str:
    """Detect known store from URL hostname."""
    host = urlparse(url).netloc.lower()
    store_map = {
        "snitch.co.in": "snitch",
        "snitch.com": "snitch",
        "fashionnova.com": "fashionnova",
        "libas.in": "libas",
        "thehouseofrare.com": "rarerabbit",
        "gymshark.com": "gymshark",
        "bombayshirts.com": "bombayshirts",
        "theloom.in": "theloom",
        "outdoorvoices.com": "outdoorvoices",
        "goodamerican.com": "goodamerican",
    }
    for domain, store in store_map.items():
        if domain in host:
            return store
    return ""
