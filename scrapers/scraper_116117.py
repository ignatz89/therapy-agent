"""
Scraper for arztsuche.116117.de — offizielle KBV-Psychotherapeutensuche.

Navigates to the psychotherapist search (ag=12), fills location + radius,
optionally applies GKV filter, and returns practice cards as dicts.
"""

import re
import time
import random
from datetime import datetime
from typing import Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, StaleElementReferenceException
)

from scrapers.base import TherapyScraper, log

# ag=12 pre-selects Psychotherapeut/Psychotherapeutin as specialty
SEARCH_URL = "https://arztsuche.116117.de/?ag=12&extendedSearch=true"

# Radius values offered by the site (in km)
_RADIUS_STEPS = [1, 2, 3, 5, 10, 20, 30, 50]


def _parse_waiting_weeks(text: str) -> Optional[int]:
    """Convert German waiting-time text to weeks (None if unknown)."""
    if not text:
        return None
    t = text.lower()
    if "sofort" in t or "kurzfristig" in t or "zeitnah" in t:
        return 0
    m = re.search(r"(\d+)\s*(?:[-–]\s*\d+)?\s*woche", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*monat", t)
    if m:
        return int(m.group(1)) * 4
    return None


def _nearest_radius(desired_km: int) -> int:
    """Return the closest radius value the site supports."""
    return min(_RADIUS_STEPS, key=lambda r: abs(r - desired_km))


class Scraper116117(TherapyScraper):
    name = "116117"

    def scrape(self, config: Dict) -> List[Dict]:
        location = config.get("location", "München")
        radius   = config.get("radius", 5)
        show_browser = config.get("show_browser", False)

        self.headless = not show_browser
        driver = self.make_driver()
        wait   = WebDriverWait(driver, 20)
        results: List[Dict] = []

        try:
            log(f"[116117] Navigiere zu Suche (ag=12, {location}, {radius} km) ...")
            driver.get(SEARCH_URL)
            time.sleep(3)

            self._dismiss_cookies(driver)
            time.sleep(1)

            self._fill_location(driver, wait, location)
            self._set_radius(driver, wait, radius)
            self._submit_search(driver, wait)
            time.sleep(5)
            import pathlib
            _data = pathlib.Path(__file__).parent.parent / "data"
            _data.mkdir(exist_ok=True)
            driver.save_screenshot(str(_data / "116117_results.png"))
            log("[116117] Screenshot nach Suche: data/116117_results.png")

            page = 1
            while True:
                log(f"[116117] Seite {page}: Ergebnisse lesen ...")
                found = self._parse_results(driver)
                results.extend(found)
                log(f"[116117] Seite {page}: {len(found)} Praxen (gesamt: {len(results)}).")

                if not found or not self._go_to_next_page(driver, wait):
                    break
                page += 1
                time.sleep(random.uniform(2.5, 4.0))

        except Exception as exc:
            log(f"[116117] Fehler: {exc}")
            try:
                import pathlib
                _data = pathlib.Path(__file__).parent.parent / "data"
                _data.mkdir(exist_ok=True)
                driver.save_screenshot(str(_data / "116117_error.png"))
                log("[116117] Screenshot gespeichert: data/116117_error.png")
            except Exception:
                pass
        finally:
            driver.quit()
            log("[116117] Browser geschlossen.")

        return results

    # ---------------------------------------------------------------------- #
    # Interaction helpers                                                      #
    # ---------------------------------------------------------------------- #

    def _dismiss_cookies(self, driver) -> None:
        # Round 1: first/simple cookie banner
        selectors_r1 = [
            (By.ID,           "onetrust-accept-btn-handler"),
            (By.CSS_SELECTOR, "button[id*='accept']"),
            (By.CSS_SELECTOR, "button[class*='accept']"),
            (By.XPATH,        "//button[contains(., 'Alle akzeptieren')]"),
            (By.XPATH,        "//button[contains(., 'Akzeptieren')]"),
            (By.XPATH,        "//button[contains(., 'Zustimmen')]"),
            (By.XPATH,        "//button[contains(., 'Einverstanden')]"),
        ]
        for by, sel in selectors_r1:
            try:
                btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((by, sel)))
                btn.click()
                log("[116117] Cookie-Banner (Runde 1) bestätigt.")
                time.sleep(1.5)
                break
            except TimeoutException:
                continue

        # Round 2: ccm (cookie consent manager) modal — accept/save primary button
        selectors_r2 = [
            (By.CSS_SELECTOR, "button.ccm--save-settings.ccm--button-primary"),
            (By.CSS_SELECTOR, "button.ccm--save-settings"),
            (By.CSS_SELECTOR, "button.ccm-modal--close"),
            (By.CSS_SELECTOR, "button.ccm-dismiss-button"),
        ]
        for by, sel in selectors_r2:
            try:
                btn = WebDriverWait(driver, 4).until(EC.element_to_be_clickable((by, sel)))
                self._js_click(driver, btn)
                log("[116117] Cookie-Banner (Runde 2 ccm) bestätigt.")
                time.sleep(1.0)
                return
            except TimeoutException:
                continue

    def _js_click(self, driver, element) -> None:
        """Click via JavaScript to bypass any overlay/interception."""
        driver.execute_script("arguments[0].click();", element)

    def _pick_autocomplete(self, driver, city: str) -> bool:
        """Click the autocomplete suggestion that matches city name. Returns True on success."""
        try:
            # Wait for dropdown; look for list item whose text starts with the city name
            xpath = f"//li[starts-with(normalize-space(.), '{city}')]"
            el = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            self._js_click(driver, el)
            time.sleep(0.8)
            log(f"[116117] Autocomplete-Vorschlag für '{city}' gewählt.")
            return True
        except TimeoutException:
            pass

        # Broader fallback: any li/option containing the city
        try:
            clicked = driver.execute_script(f"""
                var items = document.querySelectorAll('li, option');
                for (var it of items) {{
                    var t = (it.innerText || it.textContent || '').trim();
                    if (t.indexOf('{city}') === 0 || t === '{city}') {{
                        it.click();
                        return true;
                    }}
                }}
                return false;
            """)
            if clicked:
                log(f"[116117] Autocomplete '{city}' via JS gewählt.")
                time.sleep(0.8)
                return True
        except Exception:
            pass
        return False

    def _react_set_value(self, driver, element, value: str) -> None:
        """Set value on a React-controlled input and fire the synthetic events React needs."""
        driver.execute_script("""
            var input = arguments[0];
            var text  = arguments[1];
            // Use native setter so React's onChange fires
            var nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            nativeSetter.call(input, text);
            input.dispatchEvent(new Event('input',  {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
        """, element, value)

    def _fill_location(self, driver, wait, location: str) -> None:
        selectors = [
            (By.CSS_SELECTOR, "input[placeholder*='PLZ']"),
            (By.CSS_SELECTOR, "input[placeholder*='Ort']"),
            (By.CSS_SELECTOR, "input[placeholder*='Postleitzahl']"),
            (By.CSS_SELECTOR, "input[placeholder*='Standort']"),
            (By.CSS_SELECTOR, "input[id*='ort']"),
            (By.CSS_SELECTOR, "input[id*='location']"),
            (By.CSS_SELECTOR, "input[id*='plz']"),
            (By.CSS_SELECTOR, "input[name*='ort']"),
            (By.CSS_SELECTOR, "input[name*='plz']"),
            (By.CSS_SELECTOR, "input[name*='location']"),
            (By.XPATH,        "//input[@type='text'][1]"),
        ]
        for by, sel in selectors:
            try:
                el = wait.until(EC.presence_of_element_located((by, sel)))
                self._js_click(driver, el)
                time.sleep(0.3)
                self._react_set_value(driver, el, location)
                time.sleep(2.0)  # wait for React to show autocomplete suggestions
                val = el.get_attribute("value") or ""
                log(f"[116117] Location field value after React set: {val!r}")

                # Try to find and click the exact city in the autocomplete dropdown
                chose = self._pick_autocomplete(driver, location)
                if not chose:
                    # Fallback: keyboard Down + Enter selects first suggestion
                    el.send_keys(Keys.DOWN)
                    time.sleep(0.5)
                    el.send_keys(Keys.RETURN)
                    time.sleep(0.8)

                log(f"[116117] Ort eingegeben: {location}")
                return
            except TimeoutException:
                continue
        log("[116117] WARNUNG: Standort-Feld nicht gefunden.")

    def _set_radius(self, driver, wait, radius_km: int) -> None:
        nearest = _nearest_radius(radius_km)
        # Try <select> elements first
        select_ids = ["radius", "umkreis", "distance", "entfernung"]
        for frag in select_ids:
            for sel in [f"select[id*='{frag}']", f"select[name*='{frag}']"]:
                try:
                    el = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                    )
                    s = Select(el)
                    opts = [(o.get_attribute("value") or "", o.text) for o in s.options]
                    log(f"[116117] Radius-Optionen: {opts}")
                    # Try to select the nearest value
                    for val, txt in opts:
                        for cand in (str(nearest), str(nearest * 1000), f"{nearest}"):
                            if cand in val or cand in txt.lower():
                                s.select_by_value(val)
                                log(f"[116117] Radius gesetzt: {txt}")
                                return
                    log(f"[116117] Radius {nearest} km nicht exakt verfügbar.")
                    return
                except TimeoutException:
                    continue

    def _submit_search(self, driver, wait) -> None:
        # Search ALL elements (not just buttons) for visible "Suchen" text
        clicked = driver.execute_script("""
            var all = Array.from(document.querySelectorAll(
                'button, a, input[type="submit"], [role="button"]'));
            for (var el of all) {
                var t = (el.innerText || el.textContent || '').trim();
                if (t === 'Suchen' || t.startsWith('Suchen')) {
                    el.click();
                    return true;
                }
            }
            return false;
        """)
        if clicked:
            log("[116117] Suche gestartet (JS-Klick auf Suchen-Button).")
            return

        # Fallback: try CSS/XPath with explicit presence wait + JS click
        selectors = [
            (By.CSS_SELECTOR, "button[type='submit']"),
            (By.CSS_SELECTOR, "input[type='submit']"),
            (By.CSS_SELECTOR, "button[id*='suchen']"),
            (By.CSS_SELECTOR, "button[id*='search']"),
        ]
        for by, sel in selectors:
            try:
                el = WebDriverWait(driver, 3).until(EC.presence_of_element_located((by, sel)))
                self._js_click(driver, el)
                log("[116117] Suche gestartet (Fallback-Button).")
                return
            except TimeoutException:
                continue

        log("[116117] WARNUNG: Suchen-Button nicht gefunden — sende Enter.")
        try:
            driver.find_element(By.CSS_SELECTOR, "input[type='text']").send_keys(Keys.RETURN)
        except NoSuchElementException:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.RETURN)

    def _go_to_next_page(self, driver, wait) -> bool:
        selectors = [
            (By.CSS_SELECTOR, "a[aria-label*='nächste Seite']"),
            (By.CSS_SELECTOR, "a[aria-label*='next']"),
            (By.CSS_SELECTOR, "a.next-page"),
            (By.CSS_SELECTOR, "li.next a"),
            (By.CSS_SELECTOR, "a[rel='next']"),
            (By.XPATH,         "//a[contains(., 'Weiter')]"),
            (By.XPATH,         "//a[contains(., 'nächste')]"),
            (By.XPATH,         "//button[contains(., 'Weiter')]"),
        ]
        for by, sel in selectors:
            try:
                el = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((by, sel)))
                el.click()
                time.sleep(2.5)
                return True
            except TimeoutException:
                continue
        return False

    # ---------------------------------------------------------------------- #
    # Result parsing                                                           #
    # ---------------------------------------------------------------------- #

    def _parse_results(self, driver) -> List[Dict]:
        cards = driver.find_elements(By.CSS_SELECTOR, "div.praxis-list-element")
        if not cards:
            log("[116117] Keine Ergebniskarten gefunden (div.praxis-list-element).")
            log("[116117] Seiten-Vorschau:")
            try:
                try:
                    raw = driver.find_element(By.TAG_NAME, "main").text[:600]
                except NoSuchElementException:
                    raw = driver.find_element(By.TAG_NAME, "body").text[:600]
                preview = raw.encode("ascii", errors="replace").decode("ascii")
                log(preview)
            except Exception:
                pass
            return []

        log(f"[116117] {len(cards)} Ergebniskarten gefunden.")
        practices = []
        for card in cards:
            try:
                p = self._extract_practice(card)
                if not p.get("name"):
                    continue
                # Skip child/adolescent therapists
                tt_lower = p.get("therapy_types", "").lower()
                if "kinder" in tt_lower and ("jugend" in tt_lower or "kjp" in tt_lower):
                    log(f"  - Übersprungen (KJP): {p['name']}")
                    continue
                practices.append(p)
                name_safe = p["name"].encode("ascii", errors="replace").decode("ascii")
                log(f"  + {name_safe} | {p.get('address', '')}")
            except StaleElementReferenceException:
                continue
        return practices

    def _extract_practice(self, card) -> Dict:
        """Pull fields from a div.praxis-list-element card."""

        def txt(selector: str) -> str:
            try:
                by = By.XPATH if selector.startswith("//") else By.CSS_SELECTOR
                return card.find_element(by, selector).text.strip()
            except NoSuchElementException:
                return ""

        def atxt(*selectors: str) -> str:
            for sel in selectors:
                t = txt(sel)
                if t:
                    return t
            return ""

        name = atxt("h1.praxisname .link-like", "h1.praxisname span", "h1.praxisname")
        therapy_types = atxt("div.arztgruppe", ".arztgruppe")
        address_el_texts = []
        try:
            addr_div = card.find_element(By.CSS_SELECTOR, "div[aria-description='Adresse der Praxis']")
            address_el_texts = [d.text.strip() for d in addr_div.find_elements(By.CSS_SELECTOR, "div") if d.text.strip()]
        except NoSuchElementException:
            pass
        address = ", ".join(address_el_texts)

        # Website URL — cards use id="web_praxisN" for the practice website link
        url = ""
        try:
            web_el = card.find_element(By.CSS_SELECTOR, "a[id^='web_']")
            url = web_el.get_attribute("href") or ""
        except NoSuchElementException:
            pass

        # Phone
        phone = ""
        try:
            tel_el = card.find_element(By.CSS_SELECTOR, "a[href^='tel:']")
            phone = (tel_el.get_attribute("href") or "").replace("tel:", "").strip()
        except NoSuchElementException:
            pass

        return {
            "name":            name,
            "address":         address,
            "therapy_types":   therapy_types,
            "payment":         "Kassenpatienten (GKV)",  # 116117 is the official GKV portal
            "specialisations": "",
            "waiting_time":    "",
            "waiting_weeks":   None,
            "session_format":  "",
            "gender":          "",
            "phone":           phone,
            "url":             url,
            "source":          self.name,
            "scraped_at":      datetime.now().isoformat(timespec="seconds"),
        }
