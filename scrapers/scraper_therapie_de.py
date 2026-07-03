"""
Scraper for therapie.de — psychotherapist list with profile-level waiting times.

Strategy:
  1. Fetch list pages (static TYPO3 HTML) via Selenium to handle any cookies.
  2. For each practice, fetch the profile page via urllib to extract waiting time,
     therapy methods, specialisations, and payment type (GKV vs. Selbstzahler).
  3. Limit list pages via config key 'max_pages' (default 1 ≈ 100 results).
"""

import re
import time
import random
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException

from scrapers.base import TherapyScraper, log

BASE_URL    = "https://www.therapie.de"
SEARCH_URL  = BASE_URL + "/therapeutensuche/ergebnisse/"
CARD_SEL    = "li.panel.panel-default"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _parse_waiting_weeks(text: str) -> Optional[int]:
    if not text:
        return None
    t = text.lower()
    if "vorhanden" in t or "sofort" in t or "kurzfristig" in t or "zeitnah" in t:
        return 0
    if "keine" in t and ("frei" in t or "platz" in t or "plätze" in t):
        return None
    if "nicht angegeben" in t or "keine angabe" in t:
        return None
    m = re.search(r"(\d+)\s*(?:[-–]\s*\d+)?\s*woche", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*monat", t)
    if m:
        return int(m.group(1)) * 4
    return None


def _fetch_html(url: str) -> str:
    """Fetch a URL via urllib with browser-like headers."""
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "de-DE,de;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log(f"[therapie.de] Fetch-Fehler {url}: {exc}")
        return ""


def _text_after(html: str, heading: str, chars: int = 300) -> str:
    """Return plain text after `heading` when it appears as element text (preceded by '>')."""
    # Allow optional whitespace between > and the heading text
    m = re.search(r">\s*" + re.escape(heading), html)
    if not m:
        return ""
    idx = m.end() - len(heading)  # position at start of heading text
    snippet = html[idx + len(heading): idx + len(heading) + chars]
    # Strip complete tags, then remove partial open tag at end
    cleaned = re.sub(r"<[^>]+>", " ", snippet)
    cleaned = re.sub(r"<[^>]*$", "", cleaned)
    # Reject if HTML artefacts remain (e.g. "> from attribute close)
    if re.search(r'[<>"]', cleaned):
        return ""
    return cleaned.strip()


def _scrape_profile(profile_url: str) -> Dict:
    """Fetch a therapie.de profile page and extract structured data."""
    html = _fetch_html(profile_url)
    if not html:
        return {}

    def section(heading: str) -> str:
        return _text_after(html, heading)

    # Waiting time section
    wait_raw   = section("Freie Pl&#xe4;tze / Wartezeiten") or section("Freie Plätze / Wartezeiten")
    wait_clean = re.sub(r"\s+", " ", wait_raw).strip()

    # Payment / insurance — check for positive GKV indicators only
    # "Kassenzulassung" alone is ambiguous (appears in "Keine Kassenzulassung" too)
    html_lower = html.lower()
    has_gkv = bool(
        re.search(r"kassenpatienten", html_lower) or
        re.search(r"gesetzliche\s+krankenversicherung", html_lower) or
        re.search(r"\bgkv\b", html_lower) or
        re.search(r"kassenpatient(?:en)?\s+(?:werden\s+)?(?:akzeptiert|behandelt|angenommen)", html_lower) or
        (re.search(r"kassenzulassung", html_lower) and not re.search(r"keine\s+kassenzulassung|ohne\s+kassenzulassung", html_lower))
    )
    has_pkv_only = bool(
        re.search(r"private\s+krankenversicherung", html_lower) or
        re.search(r"\bpkv\b", html_lower) or
        re.search(r"selbstzahler", html_lower)
    )

    if has_gkv:
        payment = "Kassenpatienten (GKV)"
        is_gkv = True
    elif has_pkv_only:
        payment = "Selbstzahler / PKV"
        is_gkv = False
    else:
        payment = ""
        is_gkv = None

    # Therapy methods
    verfahren_raw = section("Verfahren")
    verfahren = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", ", ", verfahren_raw)).strip(", ")

    # Specialisations
    schwerpunkt_raw = section("Behandlungs-Schwerpunkte") or section("Schwerpunkte")
    specialisations = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", ", ", schwerpunkt_raw)).strip(", ")

    # Website link
    website = ""
    m = re.search(r'itemprop="url"[^>]*href="(https?://[^"]+)"', html)
    if not m:
        m = re.search(r'href="(https?://(?!www\.therapie\.de)[^"]+)"', html)
    if m:
        website = m.group(1)

    return {
        "waiting_time":    wait_clean[:120],
        "waiting_weeks":   _parse_waiting_weeks(wait_clean),
        "payment":         payment,
        "is_gkv":          is_gkv,
        "therapy_types":   verfahren[:200],
        "specialisations": specialisations[:200],
        "url":             profile_url,
        "website":         website,
    }


# --------------------------------------------------------------------------- #
# Scraper                                                                      #
# --------------------------------------------------------------------------- #

class ScraperTherapieDe(TherapyScraper):
    name = "therapie_de"

    def scrape(self, config: Dict) -> List[Dict]:
        location     = config.get("location", "München")
        radius       = config.get("radius", 5)
        kassenpat    = config.get("kassenpatienten", True)
        show_browser = config.get("show_browser", False)
        max_pages    = config.get("max_pages_therapie_de", 1)

        self.headless = not show_browser
        driver = self.make_driver()
        wait   = WebDriverWait(driver, 15)
        all_cards: List[Dict] = []  # raw list data

        try:
            params = {"ort": location, "umkreis": radius}
            if kassenpat:
                params["kasse"] = 1
            base_qs = urllib.parse.urlencode(params)

            page   = 1
            chash  = None

            while page <= max_pages:
                if page == 1:
                    url = f"{SEARCH_URL}?{base_qs}"
                else:
                    url = f"{SEARCH_URL}?{base_qs}&page={page}&cHash={chash}"

                log(f"[therapie.de] Seite {page}/{max_pages}: {url}")
                driver.get(url)
                time.sleep(3)

                if page == 1:
                    self._dismiss_cookies(driver)
                    # Extract cHash for subsequent pages
                    chash = self._get_chash(driver)

                cards = driver.find_elements(By.CSS_SELECTOR, CARD_SEL)
                if not cards:
                    log("[therapie.de] Keine Karten mehr — Ende.")
                    break

                log(f"[therapie.de] {len(cards)} Karten auf Seite {page}.")
                for card in cards:
                    try:
                        raw = self._extract_list_card(card)
                        if raw.get("name"):
                            all_cards.append(raw)
                    except StaleElementReferenceException:
                        continue

                page += 1
                if page <= max_pages and chash:
                    time.sleep(random.uniform(1.5, 2.5))

        except Exception as exc:
            log(f"[therapie.de] Scraping-Fehler: {exc}")
        finally:
            driver.quit()
            log("[therapie.de] Browser geschlossen.")

        if not all_cards:
            return []

        # Visit profile pages via urllib for waiting time + details
        log(f"[therapie.de] Lade {len(all_cards)} Profile ...")
        results: List[Dict] = []
        for i, card in enumerate(all_cards, 1):
            profile_url = card.get("profile_url", "")
            if not profile_url:
                continue
            profile = _scrape_profile(profile_url)

            # Skip child/adolescent therapists — they don't treat adults
            desc_lower = (card.get("description", "") + profile.get("therapy_types", "")).lower()
            if "kinder" in desc_lower and ("jugend" in desc_lower or "kjp" in desc_lower):
                log(f"[therapie.de] Übersprungen (KJP, kein Erwachsenenangebot): {card.get('name', '?')}")
                continue

            # Strict GKV filter: only include if explicitly identified as GKV
            if kassenpat and profile.get("is_gkv") is not True:
                log(f"[therapie.de] Übersprungen (kein GKV-Nachweis): {card.get('name', '?')}")
                continue

            practice = {**card, **profile}
            practice.setdefault("url", profile_url)
            results.append(practice)

            if i % 10 == 0:
                log(f"[therapie.de] {i}/{len(all_cards)} Profile geladen ...")
            time.sleep(random.uniform(0.4, 0.8))

        log(f"[therapie.de] {len(results)} Praxen nach GKV-Filter.")
        return results

    # ---------------------------------------------------------------------- #
    # Helpers                                                                  #
    # ---------------------------------------------------------------------- #

    def _dismiss_cookies(self, driver) -> None:
        for sel in [
            "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
            "button[id*='accept']",
            "button[class*='accept']",
            "//button[contains(., 'Alle akzeptieren')]",
            "//button[contains(., 'Akzeptieren')]",
            "//button[contains(., 'Zustimmen')]",
        ]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                log("[therapie.de] Cookie-Banner bestätigt.")
                time.sleep(0.8)
                return
            except TimeoutException:
                continue

    def _get_chash(self, driver) -> Optional[str]:
        """Extract the TYPO3 cHash from page-2 pagination link."""
        try:
            links = driver.find_elements(By.CSS_SELECTOR, "a[href*='page=2']")
            for a in links:
                href = a.get_attribute("href") or ""
                m = re.search(r"cHash=([a-f0-9]+)", href)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return None

    def _extract_list_card(self, card) -> Dict:
        """Pull name, address, phone and profile URL from a list card."""
        def txt(sel: str) -> str:
            try:
                return card.find_element(By.CSS_SELECTOR, sel).text.strip()
            except NoSuchElementException:
                return ""

        name = txt("div.search-results-name")
        desc = txt("span[itemprop='description']")
        street = txt("span[itemprop='streetAddress']")
        plz    = txt("span[itemprop='postalCode']")
        city   = txt("span[itemprop='addressLocality']")
        phone  = txt("span[itemprop='telephone']")
        address = ", ".join(filter(None, [f"{street}", f"{plz} {city}".strip()]))

        profile_url = ""
        try:
            a = card.find_element(By.CSS_SELECTOR, "a[href^='/profil/']")
            href = a.get_attribute("href") or ""
            profile_url = href if href.startswith("http") else BASE_URL + href
        except NoSuchElementException:
            pass

        return {
            "name":        name,
            "address":     address,
            "phone":       phone,
            "description": desc,
            "profile_url": profile_url,
            "source":      self.name,
            "scraped_at":  datetime.now().isoformat(timespec="seconds"),
        }
