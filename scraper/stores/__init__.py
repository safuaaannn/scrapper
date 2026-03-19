"""Store-specific scrapers — kept as reliable overrides for known stores."""

from .snitch import scrape_snitch
from .fashionnova import scrape_fashionnova
from .libas import scrape_libas
from .rarerabbit import scrape_rarerabbit
from .gymshark import scrape_gymshark
from .bombayshirts import scrape_bombayshirts
from .theloom import scrape_theloom
from .outdoorvoices import scrape_outdoorvoices
from .goodamerican import scrape_goodamerican

STORE_SCRAPERS = {
    "snitch": scrape_snitch,
    "fashionnova": scrape_fashionnova,
    "libas": scrape_libas,
    "rarerabbit": scrape_rarerabbit,
    "gymshark": scrape_gymshark,
    "bombayshirts": scrape_bombayshirts,
    "theloom": scrape_theloom,
    "outdoorvoices": scrape_outdoorvoices,
    "goodamerican": scrape_goodamerican,
}

__all__ = ["STORE_SCRAPERS"]
