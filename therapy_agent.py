"""
AI-powered therapy search agent.

Scrapes enabled platforms for therapy practices, scores them against your
profile with Claude, and prints results to the terminal sorted by waiting time.

Setup (run once):
    pip install anthropic selenium
    setx ANTHROPIC_API_KEY your-key-here   (then restart terminal)

Usage:
    py therapy_agent.py
"""

import configparser
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import anthropic

SCRIPT_DIR   = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

CONFIG_FILE  = SCRIPT_DIR / "config" / "config.ini"
PROFILE_FILE = SCRIPT_DIR / "profiles" / "marc.txt"
PROMPT_FILE  = SCRIPT_DIR / "config" / "agent_prompt.txt"
DATA_DIR     = SCRIPT_DIR / "data"

from skills.practice_store import (
    load_store, save_store, store_scraped, store_scored,
    load_ids, save_ids, practice_id, deduplicate, filter_unseen,
)
from skills.claude_scorer import score_practices
from skills.telegram import send_messages, e as _e
from scrapers import REGISTRY as SCRAPER_REGISTRY


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #

def load_config() -> Dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")
    cfg = configparser.ConfigParser(inline_comment_prefixes=("#",))
    cfg.read(CONFIG_FILE, encoding="utf-8")

    return {
        "therapy_types":    [t.strip() for t in cfg.get("search", "therapy_types", fallback="").split(",") if t.strip()],
        "location":         cfg.get("search",      "location",           fallback="").strip(),
        "radius":           cfg.getint("search",   "radius",             fallback=15),
        "min_score":        cfg.getint("search",   "min_score",          fallback=6),
        "show_browser":     cfg.getboolean("search", "show_browser",     fallback=False),
        "kassenpatienten":  cfg.getboolean("payment", "kassenpatienten", fallback=True),
        "privatpatient":    cfg.getboolean("payment", "privatpatient",   fallback=False),
        "selbstzahler":     cfg.getboolean("payment", "selbstzahler",    fallback=False),
        "therapist_gender": cfg.get("preferences", "therapist_gender",   fallback="any").strip(),
        "session_format":   [f.strip() for f in cfg.get("preferences", "session_format", fallback="einzel").split(",") if f.strip()],
        "languages":        [l.strip() for l in cfg.get("preferences", "languages", fallback="Deutsch").split(",") if l.strip()],
        "max_wait_weeks":        int(cfg.get("preferences", "max_wait_weeks", fallback="0").strip() or "0") or None,
        "ignore_unknown_wait":   cfg.getboolean("preferences", "ignore_unknown_wait", fallback=False),
        "platforms":        _load_platforms(cfg),
        "telegram_token":   cfg.get("telegram", "bot_token", fallback="").strip(),
        "telegram_chat":    cfg.get("telegram", "chat_id",   fallback="").strip(),
    }


def _load_platforms(cfg: configparser.ConfigParser) -> Dict[str, bool]:
    defaults = {"116117": True, "jameda": False, "therapeutenliste": False, "therapie_de": False, "doctolib": False, "ptk_bayern": False}
    if not cfg.has_section("platforms"):
        return defaults
    return {
        name: cfg.getboolean("platforms", name, fallback=default)
        for name, default in defaults.items()
    }


# --------------------------------------------------------------------------- #
# File loading                                                                 #
# --------------------------------------------------------------------------- #

def load_profile() -> str:
    if not PROFILE_FILE.exists():
        log("profile.txt nicht gefunden — generische Kriterien werden verwendet.")
        return "No profile provided. Evaluate therapy practices on general suitability."
    return PROFILE_FILE.read_text(encoding="utf-8").strip()


def load_agent_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Agent prompt file not found: {PROMPT_FILE}")
    lines = [l for l in PROMPT_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
             if not l.startswith("#")]
    return "".join(lines).strip()


# --------------------------------------------------------------------------- #
# Report — sorted by waiting time ascending                                    #
# --------------------------------------------------------------------------- #

def print_report(matching: List[Dict], total: int, min_score: int) -> None:
    # Sort: known waiting time ascending, unknown (None) at the end
    sorted_matches = sorted(
        matching,
        key=lambda p: (p.get("waiting_weeks") is None, p.get("waiting_weeks") or 0)
    )

    sep = "=" * 68
    print(f"\n{sep}")
    print(f"  THERAPIESUCHE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(sep)
    print(f"\n  {len(sorted_matches)} Treffer (Score >= {min_score}) von {total} bewerteten Praxen.")
    print(f"  Sortiert nach Wartezeit aufsteigend.\n")

    for i, p in enumerate(sorted_matches, 1):
        score = p.get("score", 0)
        waiting = p.get("waiting_weeks")
        wait_str = f"{waiting} Wochen" if waiting is not None else "Wartezeit unbekannt"

        print(f"  #{i:02d}  [{score:2d}/10]  Wartezeit: {wait_str}")
        print(f"        {p.get('name', 'Unbekannt')}")
        if p.get("address"):
            print(f"        {p['address']}")

        details = []
        if p.get("therapy_types"):
            details.append(p["therapy_types"])
        if p.get("payment"):
            details.append(p["payment"])
        if details:
            print(f"        {' | '.join(details)}")

        if p.get("summary"):
            print(f"        → {p['summary']}")
        if p.get("pros"):
            print(f"        ✓ " + "  /  ".join(p["pros"]))
        if p.get("cons"):
            print(f"        ✗ " + "  /  ".join(p["cons"]))
        if p.get("url"):
            print(f"        🔗 {p['url']}")
        print()

    if not sorted_matches:
        print("  Keine Treffer über dem Mindest-Score.\n")
    print(sep + "\n")


# --------------------------------------------------------------------------- #
# Core pipeline                                                                #
# --------------------------------------------------------------------------- #

def run_search(
    config: Dict,
    client: anthropic.Anthropic,
    profile: str,
    agent_prompt: str,
    scraped_practices: List[Dict],
    progress_cb=None,
) -> Dict:
    def progress(msg: str) -> None:
        log(msg)
        if progress_cb:
            progress_cb(msg)

    DATA_DIR.mkdir(exist_ok=True)
    seen_file = DATA_DIR / "seen_practices.json"
    sent_file = DATA_DIR / "sent_practices.json"
    min_score = config["min_score"]

    seen_store = load_store(seen_file)
    sent       = load_ids(sent_file)
    progress(f"Bekannte Praxen: {len(seen_store)} gesehen, {len(sent)} bereits gesendet.")

    all_scraped   = deduplicate(scraped_practices)
    new_practices = filter_unseen(all_scraped, seen_store)
    progress(f"Neue Praxen zum Bewerten: {len(new_practices)}.")

    store_scraped(seen_store, all_scraped)
    save_store(seen_file, seen_store)

    if not new_practices:
        return {"matching": [], "total_scored": 0, "new_count": 0}

    progress(f"Bewerte {len(new_practices)} Praxen mit Claude ...")
    scored = score_practices(client, new_practices, profile, agent_prompt, config)
    if not scored:
        return {"matching": [], "total_scored": 0, "new_count": len(new_practices)}

    store_scored(seen_store, scored, min_score)
    save_store(seen_file, seen_store)

    ignore_unknown = config.get("ignore_unknown_wait", False)
    matching = [
        p for p in scored
        if p.get("score", 0) >= min_score
        and practice_id(p) not in sent
        and not (ignore_unknown and p.get("waiting_weeks") is None)
    ]
    progress(f"Treffer (Score >= {min_score}): {len(matching)}.")

    return {"matching": matching, "total_scored": len(scored), "new_count": len(new_practices)}


# --------------------------------------------------------------------------- #
# Scraping                                                                     #
# --------------------------------------------------------------------------- #

def run_scrapers(config: Dict) -> List[Dict]:
    """Run every enabled platform scraper and return combined results."""
    all_practices: List[Dict] = []
    platforms = config.get("platforms", {})

    for platform_name, enabled in platforms.items():
        if not enabled:
            continue
        scraper_cls = SCRAPER_REGISTRY.get(platform_name)
        if scraper_cls is None:
            log(f"Kein Scraper für '{platform_name}' — übersprungen.")
            continue
        log(f"Scrape {platform_name} ...")
        scraper = scraper_cls(headless=not config.get("show_browser", False))
        try:
            found = scraper.scrape(config)
            log(f"{platform_name}: {len(found)} Praxen gefunden.")
            all_practices.extend(found)
        except Exception as exc:
            log(f"{platform_name} Fehler: {exc}")

    return all_practices


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main() -> None:
    # Force UTF-8 output so German umlauts and Unicode symbols print correctly on Windows
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY ist nicht gesetzt.\n"
            "Key holen: https://console.anthropic.com\n"
            "Dann: setx ANTHROPIC_API_KEY dein-key  (Terminal neu starten)"
        )

    config       = load_config()
    agent_prompt = load_agent_prompt()
    profile      = load_profile()
    log(f"Profil geladen ({len(profile)} Zeichen).")

    client = anthropic.Anthropic(api_key=api_key)

    log("Scraping wird gestartet ...")
    scraped: List[Dict] = run_scrapers(config)
    if not scraped:
        log("Keine Praxen gefunden. Prüfe ob Selenium korrekt installiert ist und die Seite erreichbar ist.")
        return

    result = run_search(config, client, profile, agent_prompt, scraped)

    if result["new_count"] == 0:
        log("Keine neuen Praxen. Später erneut versuchen.")
        return
    if result["total_scored"] == 0:
        log("Claude hat keine Ergebnisse zurückgegeben.")
        return

    token = config.get("telegram_token", "")
    chat  = config.get("telegram_chat", "")
    telegram_ready = bool(token and chat)

    if not telegram_ready:
        print_report(result["matching"], result["total_scored"], config["min_score"])

    if token and chat and result["matching"]:
        log("Sende Ergebnisse per Telegram ...")
        _send_telegram(token, chat, result["matching"], config["min_score"])
        log("Telegram-Benachrichtigung gesendet.")


def _send_telegram(token: str, chat_id: str, matching: List[Dict], min_score: int) -> None:
    sorted_matches = sorted(
        matching,
        key=lambda p: (p.get("waiting_weeks") is None, p.get("waiting_weeks") or 0)
    )
    header = [f"<b>Therapiesuche — {len(sorted_matches)} Treffer (Score ≥ {min_score})</b>\n\n"]
    blocks = header
    for i, p in enumerate(sorted_matches, 1):
        score    = p.get("score", 0)
        waiting  = p.get("waiting_weeks")
        wait_str = f"{waiting} Wochen" if waiting is not None else "Wartezeit unbekannt"
        url      = p.get("url", "")
        name     = _e(p.get("name", "Unbekannt"))

        title_html = f'<a href="{_e(url)}">{name}</a>' if url else f"<b>{name}</b>"
        lines = [f"<b>#{i} [{score}/10]</b> {title_html}"]
        if p.get("address"):
            lines.append(_e(p["address"]))
        detail = f"⏳ {_e(wait_str)}"
        if p.get("payment"):
            detail += f"  |  {_e(p['payment'])}"
        lines.append(detail)
        if p.get("therapy_types"):
            lines.append(_e(p["therapy_types"][:100]))
        if p.get("summary"):
            lines.append(f"<i>{_e(p['summary'])}</i>")
        if p.get("pros"):
            lines.append("✅ " + "  /  ".join(_e(x) for x in p["pros"]))
        if p.get("cons"):
            lines.append("⚠️ " + "  /  ".join(_e(x) for x in p["cons"]))
        blocks.append("\n".join(lines) + "\n\n")

    send_messages(token, chat_id, blocks)


if __name__ == "__main__":
    main()
