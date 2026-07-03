"""
Skill: Telegram Bot API
  URL:  https://api.telegram.org/bot{token}/{method}
  Docs: https://core.telegram.org/bots/api
  Cost: free — no additional API key required (token comes from BotFather)
  Limits: 30 messages/second globally, 1 message/second per chat

Methods used:
  getUpdates  — long polling for incoming messages (blocks up to `timeout` seconds)
  sendMessage — send a text message to a specific chat

Long polling note: only ONE client may call getUpdates at a time.
Running two instances simultaneously causes HTTP 409 Conflict.

Message length: Telegram caps messages at ~4096 characters.
send_messages() splits a list of text blocks automatically at MAX_MSG_LEN.
"""

import html as _html
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

MAX_MSG_LEN = 4000


def e(text: str) -> str:
    """HTML-escape for safe insertion into HTML-formatted Telegram messages."""
    return _html.escape(str(text))


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _tg_request(
    token: str,
    method: str,
    payload: Optional[Dict] = None,
    params: Optional[Dict] = None,
) -> Optional[Dict]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        _log(f"Telegram {method} failed: {exc}")
        return None


def get_updates(token: str, offset: int, timeout: int = 30) -> List[Dict]:
    """Long-poll for new updates. Returns list of update dicts (may be empty)."""
    result = _tg_request(token, "getUpdates", params={"timeout": timeout, "offset": offset})
    if result and result.get("ok"):
        return result.get("result", [])
    return []


def send_message(token: str, chat_id: str, text: str) -> None:
    """Send a single HTML-formatted message. Silently skips empty text."""
    if not text.strip():
        return
    _tg_request(token, "sendMessage", payload={
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    })


def send_messages(token: str, chat_id: str, blocks: List[str]) -> None:
    """Send a list of text blocks, merging and splitting at MAX_MSG_LEN."""
    current = ""
    for block in blocks:
        if len(current) + len(block) > MAX_MSG_LEN:
            send_message(token, chat_id, current.strip())
            time.sleep(0.4)
            current = block
        else:
            current += block
    if current.strip():
        send_message(token, chat_id, current.strip())
