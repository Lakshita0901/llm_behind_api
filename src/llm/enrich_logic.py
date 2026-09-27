"""
src/llm/enrich_logic.py
Core LLM orchestration:
  - Loads the versioned prompt from prompts/enrich-v1.md
  - Sends book record as a separate user message (never in system prompt)
  - Parses + validates response against EnrichOutput schema
  - One repair retry on failure
  - Quarantines failures to logs/quarantine.jsonl
  - Logs cost/usage data per call
  - Handles timeout → 504, 429/5xx with backoff+jitter, never retries 400/401/403

Quarantine log format (one JSON line per failure):
  {"ts":..., "prompt_version":..., "model":..., "repaired":bool,
   "error":..., "raw_output":..., "input":{...}}
"""
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from src.llm.client import client, MODEL
from src.llm.schema import EnrichOutput

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = ROOT / "prompts" / "enrich-v1.md"
QUARANTINE_PATH = ROOT / "logs" / "quarantine.jsonl"
PROMPT_VERSION = "enrich-v1"

# ── Retry policy ──────────────────────────────────────────────────────────────
# Retry on: timeout, 429, 5xx.  NEVER on: 400, 401, 403.
MAX_RETRIES = 3          # explicit count — do not rely on SDK default
BASE_BACKOFF = 1.0       # seconds (doubles each attempt: 1, 2, 4)
MAX_BACKOFF = 8.0
JITTER_MAX = 0.5         # add up to 0.5s random jitter


def _load_system_prompt() -> str:
    """Load the versioned prompt file. Cached in-process."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def _quarantine(*, raw: str, book_input: dict, error: str, repaired: bool) -> None:
    """Append a failure record to logs/quarantine.jsonl."""
    QUARANTINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "prompt_version": PROMPT_VERSION,
        "model": MODEL,
        "repaired": repaired,
        "error": error,
        "raw_output": raw,
        "input": book_input,
    }
    with open(QUARANTINE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    logger.warning("Quarantined bad model output. Error: %s", error)


def _log_call(
    *,
    prompt_version: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: float,
    repaired: bool,
) -> None:
    """Log one structured line per model call."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": round(duration_ms, 1),
        "repaired": repaired,
    }
    logger.info("COST_LOG %s", json.dumps(record))


def _strip_fences(text: str) -> str:
    """Remove markdown code fences from model output."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\n?```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def _extract_json_object(text: str) -> str:
    """Find the first complete JSON object in text."""
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output")
    # Walk to find matching closing brace
    depth = 0
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ValueError("Unmatched braces in model output")


def _parse_and_validate(raw: str) -> EnrichOutput:
    """Strip fences, extract JSON, validate against schema. Raises on failure."""
    cleaned = _strip_fences(raw)
    json_str = _extract_json_object(cleaned)
    data = json.loads(json_str)
    return EnrichOutput(**data)


def _should_retry(exc: Exception) -> tuple[bool, float]:
    """Return (should_retry, wait_seconds). Never retry 400/401/403."""
    if isinstance(exc, APITimeoutError):
        return True, 0.0
    if isinstance(exc, APIStatusError):
        code = exc.status_code
        if code in (400, 401, 403):
            return False, 0.0
        if code == 429 or code >= 500:
            # Respect Retry-After header if present
            retry_after = exc.response.headers.get("Retry-After")
            if retry_after:
                try:
                    return True, float(retry_after)
                except ValueError:
                    pass
            return True, 0.0
    if isinstance(exc, APIConnectionError):
        return True, 0.0
    return False, 0.0


def _call_model(messages: list, attempt: int = 0) -> tuple[str, int, int]:
    """
    Call the model with exponential backoff+jitter retry.
    Returns (content, input_tokens, output_tokens).
    Raises the final exception after MAX_RETRIES.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=0.2,
                max_tokens=300,
            )
            content = resp.choices[0].message.content or ""
            usage = resp.usage
            in_tok = usage.prompt_tokens if usage else 0
            out_tok = usage.completion_tokens if usage else 0
            return content, in_tok, out_tok

        except Exception as exc:
            retry, wait = _should_retry(exc)
            if not retry or attempt == MAX_RETRIES:
                raise
            # Exponential backoff with jitter
            backoff = min(BASE_BACKOFF * (2 ** attempt), MAX_BACKOFF)
            jitter = random.uniform(0, JITTER_MAX)
            sleep_time = max(wait, backoff) + jitter
            logger.warning(
                "LLM call failed (attempt %d/%d): %s — retrying in %.2fs",
                attempt + 1, MAX_RETRIES, exc, sleep_time,
            )
            time.sleep(sleep_time)

    # Should not reach here
    raise RuntimeError("Retry loop exhausted unexpectedly")


def enrich_book(book_input: dict) -> EnrichOutput:
    """
    Main entry point. Raises:
      - APITimeoutError   → caller turns into 504
      - APIStatusError    → caller turns into 502 or re-raises
      - ValueError("quarantined") → caller turns into 422
    """
    system_prompt = _load_system_prompt()
    user_message = json.dumps(book_input, ensure_ascii=False)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    start = time.monotonic()

    # ── First attempt ─────────────────────────────────────────────────────────
    raw, in_tok, out_tok = _call_model(messages)
    duration_ms = (time.monotonic() - start) * 1000

    # ── Parse + validate ──────────────────────────────────────────────────────
    repaired = False
    try:
        result = _parse_and_validate(raw)
        _log_call(
            prompt_version=PROMPT_VERSION,
            model=MODEL,
            input_tokens=in_tok,
            output_tokens=out_tok,
            duration_ms=duration_ms,
            repaired=False,
        )
        return result
    except (json.JSONDecodeError, ValueError, ValidationError) as first_err:
        _first_err = first_err  # save before Python 3 deletes the 'as' binding on block exit
        logger.warning("First parse failed: %s — attempting repair", _first_err)

    # ── One repair retry ──────────────────────────────────────────────────────
    repair_messages = messages + [
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                f"Your previous answer was rejected for this reason: {_first_err}\n"
                "Return only corrected JSON matching the schema exactly. "
                "No prose, no fences, just the JSON object."
            ),
        },
    ]

    raw2 = raw  # fallback: use first raw output if repair call itself fails
    in_tok2, out_tok2 = 0, 0
    repair_start = time.monotonic()
    try:
        raw2, in_tok2, out_tok2 = _call_model(repair_messages)
        repair_duration_ms = (time.monotonic() - repair_start) * 1000

        result = _parse_and_validate(raw2)
        _log_call(
            prompt_version=PROMPT_VERSION,
            model=MODEL,
            input_tokens=in_tok + in_tok2,
            output_tokens=out_tok + out_tok2,
            duration_ms=duration_ms + repair_duration_ms,
            repaired=True,
        )
        return result

    except (json.JSONDecodeError, ValueError, ValidationError) as repair_err:
        # Both attempts failed — quarantine and raise
        _quarantine(
            raw=raw2,
            book_input=book_input,
            error=str(repair_err),
            repaired=True,
        )
        _log_call(
            prompt_version=PROMPT_VERSION,
            model=MODEL,
            input_tokens=in_tok + in_tok2,
            output_tokens=out_tok + out_tok2,
            duration_ms=(time.monotonic() - start) * 1000,
            repaired=True,
        )
        raise ValueError(f"quarantined: {repair_err}") from repair_err
