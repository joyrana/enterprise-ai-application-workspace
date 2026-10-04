"""Extract a JSON object from model text that may contain reasoning traces or chatter.

Open-weight models commonly wrap JSON in extra text:

* Qwen-family reasoning blocks: ``<think> … </think>``.
* gpt-oss "harmony" channel markers leaking into content:
  ``<|channel|>analysis<|message|> … <|end|><|start|>assistant<|channel|>final<|message|>{…}``.
* Markdown code fences and commentary before or after the JSON.

Extraction is deterministic and conservative: it returns the first complete,
parseable top-level JSON object, or raises :class:`ExtractionError`.
"""

from __future__ import annotations

import json
import re
from typing import Any

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)
_HARMONY_FINAL = "<|channel|>final<|message|>"
_HARMONY_TOKENS = re.compile(r"<\|(?:end|return|start|call|channel|message|constrain)\|>")


class ExtractionError(ValueError):
    pass


def strip_reasoning(text: str) -> str:
    """Remove reasoning traces and harmony framing, keeping the final answer text."""
    if _HARMONY_FINAL in text:
        text = text.rsplit(_HARMONY_FINAL, 1)[1]
    text = _THINK.sub("", text)
    # A <think> block that never closes contains no answer we can trust after it.
    text = _UNCLOSED_THINK.sub("", text)
    text = _HARMONY_TOKENS.sub("", text)
    return text.strip()


def _scan_object(text: str, start: int) -> int | None:
    """Return the index just past the balanced object starting at ``start``, or None."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = strip_reasoning(text)
    if not cleaned:
        raise ExtractionError("the response contained no answer text")
    position = 0
    last_error: str | None = None
    while True:
        start = cleaned.find("{", position)
        if start == -1:
            break
        end = _scan_object(cleaned, start)
        if end is None:
            last_error = "a JSON object was started but never closed (truncated output?)"
            break
        candidate = cleaned[start:end]
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = f"invalid JSON: {exc.msg} at char {exc.pos}"
            position = start + 1
            continue
        if isinstance(value, dict):
            return value
        position = end
    raise ExtractionError(last_error or "no JSON object found in the response")
