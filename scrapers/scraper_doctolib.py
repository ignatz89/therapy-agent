"""
Scraper for doctolib.de — psychotherapist search with real availability.

Strategy:
  1. Fetch search results page via Selenium (React SPA, needs JS).
  2. Extract doctor cards (name, address, profile URL, next availability).
  3. GKV filter applied via URL parameter insurance_sector=public.
  4. Paginate via 'page' parameter.
"""

import re
import time
import random
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import quote

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException

from scrapers.base import TherapyScraper, log

BASE_URL = "https://www.doctolib.de"

# Specialties to search (tried in order)
_SPECIALTIES = ["psychotherapeut", "psychologischer-psychotherapeut"]

# Card selectors — Doctolib React SPA, try multiple
_CARD_SELS = [
    "div[data-test='search-result-card']",
    "div[data-test-id='search-result-card']",
    "article[class*='search-result']",
    "div[class*='dl-search-result']",
    "div[class*='searchCard']",
    "div[class*='SearchResult']",
]

_NAME_SELS = [
    "h3[data-test='doctor-name']",
    "[data-test='doctor-name']",
    "h3[class*='name']",
    "h2[class*='name']",
    "[class*='profileName']",
    "[class*='doctorName']",
]

_ADDRESS_SELS = [
    "[data-test='search-result-doctor-address']",
    "[class*='address']",
    "[class*='location']",
]

_AVAIL_SELS = [
    "[data-test='search-result-next-slots']",
    "[class*='availability']",
    "[class*='nextSlot']",
    "[class*='Slot']",
]


def _city_slug(city: str) -> str:
    """Convert city name to Doctolib URL slug (München → muenchen)."""
    slug = city.lower().strip()
    slug = slug.replace("ü", "ue").replace("ä", "ae").replace("ö", "oe").replace("ß", "ss")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


def _parse_waiting_weeks(text: str) -> Optional[int]:
    if not text:
        return None
    t = text.lower()
    if any(w in t for w in ["heute", "morgen", "sofort", "verfügbar", "heute"]):
        return 0
    if "diese woche" in t or "this week" in t:
        return 0
    m = re.search(r"(\d+)\s*(?:[-–]\s*\d+)?\s*woche", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*monat", t)
    if m:
        return int(m.group(1)) * 4
    return None


class ScraperDoctolib(TherapyScraper):
    name = "doctolib"

    def scrape(self, config: Dict) -> List[Dict]:
        location     = config.get("location", "München")
        kassenpat    = config.get("kassenpatienten", True)
        show_browser = config.get("show_browser", False)
        max_pages    = config.get("max_pages_doctolib", 2)

        self.headless = not show_browser
        city_slug = _city_slug(location)

        all_results: List[Dict] = []

        for specialty in _SPECIALTIES:
            results = self._scrape_specialty(specialty, city_slug, kassenpat, max_pages)
            all_results.extend(results)
            if results:
                break  # use first specialty that yields results

        log(f"[doctolib] {len(all_results)} Praxen gefunden.")
        return all_results

    def _scrape_specialty(self, specialty: str, city_slug: str,
                          kassenpat: bool, max_pages: int) -> List[Dict]:
        driver = self.make_driver()
        wait   = WebDriverWait(driver, 20)
        results: List[Dict] = []

        try:
            for page in range(1, max_pages + 1):
                insurance = "public" if kassenpat else ""
                url = f"{BASE_URL}/{specialty}/{city_slug}"
                params = []
                if insurance:
                    params.append(f"insurance_sector={insurance}")
                if page > 1:
                    params.append(f"page={page}")
                if params:
                    url += "?" + "&".join(params)

                log(f"[doctolib] Seite {page}/{max_pages}: {url}")
                driver.get(url)
                time.sleep(3)

                if page == 1:
                    self._dismiss_cookies(driver)
                    time.sleep(1)

                # Find cards
                cards = []
                for sel in _CARD_SELS:
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                        cards = driver.find_elements(By.CSS_SELECTOR, sel)
                        if cards:
                            log(f"[doctolib] Selektor '{sel}' → {len(cards)} Karten.")
                            break
                    except TimeoutException:
                        continue

                if not cards:
                    log("[doctolib] Keine Karten gefunden — Ende.")
                    break

                for card in cards:
                    try:
                        practice = self._extract_card(card)
                        if practice.get("name"):
                            results.append(practice)
                    except StaleElementReferenceException:
                        continue

                log(f"[doctolib] Seite {page}: {len(cards)} Karten, {len(results)} gesamt.")
                if page < max_pages:
                    time.sleep(random.uniform(2.0, 3.5))

        except Exception as exc:
            log(f"[doctolib] Fehler: {exc}")
        finally:
            driver.quit()
            log("[doctolib] Browser geschlossen.")

        return results

    def _dismiss_cookies(self, driver) -> None:
        for sel in [
            "button#didomi-notice-agree-button",
            "button[id*='agree']",
            "//button[contains(., 'Akzeptieren')]",
            "//button[contains(., 'Alle akzeptieren')]",
            "//button[contains(., 'Accept')]",
        ]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                log("[doctolib] Cookie-Banner bestätigt.")
                time.sleep(0.8)
                return
            except TimeoutException:
                continue

    def _extract_card(self, card) -> Dict:
        def txt(sels: list) -> str:
            for sel in sels:
                try:
                    return card.find_element(By.CSS_SELECTOR, sel).text.strip()
                except NoSuchElementException:
                    continue
            return ""

        name      = txt(_NAME_SELS)
        address   = txt(_ADDRESS_SELS)
        avail_raw = txt(_AVAIL_SELS)

        # Profile URL
        profile_url = ""
        try:
            a = card.find_element(By.CSS_SELECTOR, "a[href*='/psychotherapeut/'], a[href*='/psychologischer-psychotherapeut/'], a[href*='/profil/']")
            href = a.get_attribute("href") or ""
            profile_url = href if href.startswith("http") else BASE_URL + href
        except NoSuchElementException:
            try:
                a = card.find_element(By.CSS_SELECTOR, "a[href]")
                href = a.get_attribute("href") or ""
                if "/psycho" in href or "/profil" in href or "/praxi" in href:
                    profile_url = href if href.startswith("http") else BASE_URL + href
            except NoSuchElementException:
                pass

        waiting_weeks = _parse_waiting_weeks(avail_raw)

        return {
            "name":          name,
            "address":       address,
            "phone":         "",
            "description":   "",
            "profile_url":   profile_url,
            "url":           profile_url,
            "waiting_time":  avail_raw[:120],
            "waiting_weeks": waiting_weeks,
            "payment":       "Kassenpatienten (GKV)",
            "is_gkv":        True,
            "therapy_types": "",
            "specialisations": "",
            "source":        self.name,
            "scraped_at":    datetime.now().isoformat(timespec="seconds"),
        }
