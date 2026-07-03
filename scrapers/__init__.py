from scrapers.base import TherapyScraper, log
from scrapers.scraper_116117 import Scraper116117
from scrapers.scraper_therapie_de import ScraperTherapieDe
from scrapers.scraper_doctolib import ScraperDoctolib
from scrapers.scraper_ptk_bayern import ScraperPtkBayern

REGISTRY = {
    "116117":      Scraper116117,
    "therapie_de": ScraperTherapieDe,
    "doctolib":    ScraperDoctolib,
    "ptk_bayern":  ScraperPtkBayern,
}

__all__ = ["TherapyScraper", "Scraper116117", "ScraperTherapieDe", "ScraperDoctolib",
           "ScraperPtkBayern", "REGISTRY", "log"]
