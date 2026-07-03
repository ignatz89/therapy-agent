"""
Simple JSON store for therapy practices — tracks seen and sent practices
to avoid re-scoring and duplicate Telegram notifications.
"""

import json
from pathlib import Path
from typing import Dict, List, Set, Tuple


def practice_id(practice: Dict) -> str:
    name = practice.get("name") or practice.get("title") or ""
    addr = practice.get("address") or ""
    return (name + "|" + addr).strip().lower()


def load_store(path: Path) -> Dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_store(path: Path, store: Dict) -> None:
    path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ids(path: Path) -> Set[str]:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_ids(path: Path, ids: Set[str]) -> None:
    path.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=2), encoding="utf-8")


def deduplicate(practices: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for p in practices:
        pid = practice_id(p)
        if pid not in seen:
            seen.add(pid)
            out.append(p)
    return out


def filter_unseen(practices: List[Dict], store: Dict) -> List[Dict]:
    return [p for p in practices if practice_id(p) not in store]


def store_scraped(store: Dict, practices: List[Dict]) -> None:
    for p in practices:
        pid = practice_id(p)
        if pid not in store:
            store[pid] = {"status": "scraped", "data": p}


def store_scored(store: Dict, scored: List[Dict], min_score: int) -> None:
    for p in scored:
        pid = practice_id(p)
        entry = store.setdefault(pid, {})
        entry["status"] = "match" if p.get("score", 0) >= min_score else "scored"
        entry["score"]  = p.get("score", 0)
        entry["pros"]   = p.get("pros", [])
        entry["cons"]   = p.get("cons", [])
        entry["summary"] = p.get("summary", "")
