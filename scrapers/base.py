from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


class TherapyScraper(ABC):
    name: str = ""

    def __init__(self, headless: bool = True):
        self.headless = headless

    @abstractmethod
    def scrape(self, config: Dict) -> List[Dict]:
        pass

    def make_driver(self) -> webdriver.Chrome:
        log("Setting up Chrome driver ...")
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
        )
        driver = webdriver.Chrome(options=options)
        log("Browser ready.")
        return driver

    def get_text(self, element, selector: str) -> str:
        try:
            return element.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return ""
