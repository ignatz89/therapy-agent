"""
Scraper for ptk-bayern.de — Psychotherapeutenkammer Bayern therapist search.

Strategy:
  1. Open search form via Selenium (Lotus Notes/Domino web app).
  2. Fill city, radius, GKV filter, Erwachsene checkbox via JS.
  3. Click Suchen button.
  4. Parse result cards from the same page.
  5. Filter strictly: only cards with 'GKV' and 'erw' in the name attribute.
"""

import re
import time
import random
from datetime import datetime
from typing import Dict, List

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from scrapers.base import TherapyScraper, log

BASE_URL    = "https://www.ptk-bayern.de"
FORM_URL    = BASE_URL + "/ptk/web.nsf/formular?openForm&formular=depsychotherapeutensuche"
PROFILE_URL = BASE_URL + "/ptk/web.nsf/id/pa_therapeuten_details.html?OpenDocument&ID={id}"

# Radius values available in the form
_RADIUS_MAP = {0: "0", 1: "1", 2: "1", 3: "3", 4: "3", 5: "5",
               6: "5", 7: "5", 8: "8", 9: "8", 10: "10",
               15: "15", 20: "20", 99: "20"}

# Therapy method codes
_METHOD_MAP = {
    "Verhaltenstherapie": "300",
    "Tiefenpsychologisch": "2",
    "Analytisch": "1",
    "Systemisch": "400",
}


class ScraperPtkBayern(TherapyScraper):
    name = "ptk_bayern"

    def scrape(self, config: Dict) -> List[Dict]:
        location     = config.get("location", "München")
        radius       = config.get("radius", 5)
        kassenpat    = config.get("kassenpatienten", True)
        show_browser = config.get("show_browser", False)
        therapy_types = config.get("therapy_types", [])

        # Pick closest available radius
        radius_val = _RADIUS_MAP.get(radius) or "5"
        for r in sorted(_RADIUS_MAP.keys()):
            if r >= radius:
                radius_val = _RADIUS_MAP[r]
                break

        self.headless = not show_browser
        driver = self.make_driver()
        results: List[Dict] = []

        try:
            driver.get(FORM_URL)
            time.sleep(4)
            self._dismiss_cookies(driver)
            time.sleep(1)

            # Fill form
            driver.find_element(By.NAME, "field2t").send_keys(location)

            # Radius, GKV, Erwachsene via JS (some options may be disabled)
            method_val = "300"  # Verhaltenstherapie default
            for t in therapy_types:
                for k, v in _METHOD_MAP.items():
                    if k.lower() in t.lower():
                        method_val = v
                        break

            driver.execute_script(f"""
                // Radius
                var r = document.querySelector('select[name=field8t]');
                if(r) {{ r.value = '{radius_val}'; r.dispatchEvent(new Event('change',{{bubbles:true}})); }}
                // GKV
                if({1 if kassenpat else 0}) {{
                    var s = document.querySelector('select[name=field9t]');
                    if(s) {{ s.value = 'gkv'; s.dispatchEvent(new Event('change',{{bubbles:true}})); }}
                }}
                // Erwachsene checkbox
                var cb = document.querySelector('input[name=field32c]');
                if(cb) {{ cb.removeAttribute('disabled'); cb.checked = true; cb.dispatchEvent(new Event('change')); }}
                // Therapy method
                var m = document.querySelector('select[name=field10t]');
                if(m) {{ m.value = '{method_val}'; m.dispatchEvent(new Event('change',{{bubbles:true}})); }}
                // Language: Deutsch
                var l = document.querySelector('select[name=field7t]');
                if(l) {{ l.value = '3'; l.dispatchEvent(new Event('change',{{bubbles:true}})); }}
            """)
            time.sleep(0.5)

            # Click Suchen button
            suchen = driver.find_element(By.XPATH, "//input[@type='button' and contains(@value,'Suchen')]")
            driver.execute_script("arguments[0].click()", suchen)
            log(f"[ptk_bayern] Suche gestartet für '{location}', Radius {radius_val} km ...")
            time.sleep(6)

            # Parse results
            cards = driver.find_elements(By.CSS_SELECTOR, "div.row[id^='listElement']")
            log(f"[ptk_bayern] {len(cards)} Karten gefunden.")

            for card in cards:
                try:
                    p = self._extract_card(card, kassenpat)
                    if p:
                        results.append(p)
                except Exception:
                    continue

        except Exception as exc:
            log(f"[ptk_bayern] Fehler: {exc}")
        finally:
            driver.quit()
            log("[ptk_bayern] Browser geschlossen.")

        log(f"[ptk_bayern] {len(results)} GKV-Erwachsenen-Praxen nach Filter.")
        return results

    def _dismiss_cookies(self, driver) -> None:
        for sel in [
            "//button[contains(., 'Alle Cookies zulassen')]",
            "//button[contains(., 'Alle akzeptieren')]",
            "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        ]:
            try:
                by = By.XPATH if sel.startswith("//") else By.CSS_SELECTOR
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                log("[ptk_bayern] Cookie-Banner bestätigt.")
                time.sleep(0.8)
                return
            except TimeoutException:
                continue

    def _extract_card(self, card, kassenpat: bool) -> Dict:
        card_name = card.get_attribute("name") or ""

        # Strict filters
        if kassenpat and "GKV" not in card_name:
            return {}
        if "erw" not in card_name:  # only Erwachsene
            return {}

        def txt(sel: str) -> str:
            try:
                return card.find_element(By.CSS_SELECTOR, sel).text.strip()
            except NoSuchElementException:
                return ""

        # Name: bold text in first content div
        name = ""
        try:
            bolds = card.find_elements(By.TAG_NAME, "b")
            for b in bolds:
                t = b.text.strip()
                if t and "Telefon" not in t and "Email" not in t:
                    name = t
                    break
        except Exception:
            pass

        # Address and phone from divs
        divs = card.find_elements(By.CSS_SELECTOR, "div.col-xs-12")
        address = ""
        phone = ""
        email = ""
        for div in divs:
            t = div.text.strip()
            if re.match(r"\d{4,5}\s+\w", t) or (", " in t and re.search(r"\d{4,5}", t)):
                address = t
            elif t.startswith("Telefon"):
                phone = t.replace("Telefon", "").strip()
            elif "email" in div.get_attribute("class").lower() or t.startswith("Email"):
                try:
                    email = div.find_element(By.TAG_NAME, "a").text.strip()
                except Exception:
                    pass

        # Profile URL via Visitenkarte link
        profile_url = ""
        try:
            a = card.find_element(By.XPATH, ".//a[contains(text(),'Visitenkarte')]")
            href = a.get_attribute("href") or ""
            profile_url = href if href.startswith("http") else BASE_URL + href
        except NoSuchElementException:
            pass

        if not name:
            return {}

        payment = "Kassenpatienten (GKV)"
        if "PKV" in card_name:
            payment += " + PKV"

        return {
            "name":          name,
            "address":       address,
            "phone":         phone,
            "description":   email,
            "profile_url":   profile_url,
            "url":           profile_url,
            "waiting_time":  "",
            "waiting_weeks": None,
            "payment":       payment,
            "is_gkv":        True,
            "therapy_types": "",
            "specialisations": "",
            "source":        self.name,
            "scraped_at":    datetime.now().isoformat(timespec="seconds"),
        }
