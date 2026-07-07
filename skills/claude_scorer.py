"""
Skill: Claude therapy practice scorer
  Model: claude-opus-4-8 (adaptive thinking + prompt caching)

Input:
  - List of therapy practices (name, address, therapy_types, payment, url, ...)
  - Candidate profile from profiles/NAME.txt
  - Scoring instructions from agent_prompt.txt

Output format expected from Claude:
  {"scored_practices": [
    {"id": 0, "name": ..., "address": ..., "score": 8,
     "pros": [...], "cons": [...], "summary": "..."},
    ...
  ]}
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List, Optional

import anthropic

_MODEL      = "claude-opus-4-8"
_BATCH_SIZE = 20


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_json(text: str) -> str:
    match = re.search(r"\{[\s\S]*\}", text)
    return match.group(0) if match else text


def _score_batch(client, batch: List[Dict], system_prompt: str) -> List[Dict]:
    payload = [
        {"id": i, **{k: p.get(k, "") for k in
         ("name", "address", "therapy_types", "payment", "specialisations",
          "waiting_time", "session_format", "gender", "source")}}
        for i, p in enumerate(batch)
    ]
    response = client.messages.create(
        model=_MODEL,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": f"Score these {len(batch)} therapy practices and return JSON only:\n\n"
                       + json.dumps(payload, ensure_ascii=False, indent=2),
        }],
    )
    raw = next((b.text for b in response.content if b.type == "text"), "")
    usage = response.usage
    _log(
        f"  Batch tokens — input: {usage.input_tokens}, output: {usage.output_tokens}, "
        f"cache read: {getattr(usage, 'cache_read_input_tokens', 0)}"
    )
    try:
        scored = json.loads(extract_json(raw)).get("scored_practices", [])
    except (json.JSONDecodeError, AttributeError):
        _log(f"Warning: could not parse Claude response. Preview: {raw[:300]}")
        return []

    for s in scored:
        try:
            orig = batch[int(s["id"])] if int(s["id"]) < len(batch) else {}
        except (KeyError, TypeError, ValueError):
            orig = {}
        for field in ("url", "address", "therapy_types", "payment",
                      "specialisations", "waiting_weeks", "waiting_time", "source"):
            # Use orig value whenever Claude left the field empty or absent
            if not s.get(field):
                s[field] = orig.get(field, "")
    return scored


def score_practices(
    client: anthropic.Anthropic,
    practices: List[Dict],
    profile: str,
    agent_prompt: str,
    config: Optional[Dict] = None,
) -> List[Dict]:
    extra_context = ""
    if config:
        parts = []
        if config.get("therapy_types"):
            parts.append("Requested therapy types: " + ", ".join(config["therapy_types"]))
        payment = [k for k in ("kassenpatienten", "privatpatient", "selbstzahler")
                   if config.get(k)]
        if payment:
            parts.append("Accepted payment: " + ", ".join(payment))
        if config.get("therapist_gender") and config["therapist_gender"] != "any":
            parts.append(f"Therapist gender preference: {config['therapist_gender']}")
        if config.get("session_format"):
            parts.append("Session format: " + ", ".join(config["session_format"]))
        if config.get("max_wait_weeks"):
            parts.append(f"Max. waiting time: {config['max_wait_weeks']} weeks.")
        if parts:
            extra_context = "\n\n## Search Criteria\n" + "\n".join(parts)

    system_prompt = agent_prompt + "\n\n## Candidate Profile\n\n" + profile + extra_context
    batches = [practices[i:i + _BATCH_SIZE] for i in range(0, len(practices), _BATCH_SIZE)]
    if not batches:
        return []
    _log(f"Scoring {len(practices)} practices in {len(batches)} batch(es) ...")

    all_scored: List[Dict] = []
    # First batch alone warms the ephemeral prompt cache (shared system prompt/profile);
    # the rest read the warm cache and run in parallel.
    _log(f"Batch 1/{len(batches)}: {len(batches[0])} practices (warms prompt cache) ...")
    all_scored.extend(_score_batch(client, batches[0], system_prompt))

    if len(batches) > 1:
        _log(f"Scoring batches 2-{len(batches)} in parallel ...")
        with ThreadPoolExecutor(max_workers=min(4, len(batches) - 1)) as executor:
            for scored in executor.map(lambda b: _score_batch(client, b, system_prompt), batches[1:]):
                all_scored.extend(scored)

    return sorted(all_scored, key=lambda x: x.get("score", 0), reverse=True)
