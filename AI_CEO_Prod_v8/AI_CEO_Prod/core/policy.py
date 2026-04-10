from __future__ import annotations

import json
from typing import Any, Dict, List

ALLOWED_BROWSER_KEYS = {"url", "click", "type", "selector", "extract", "wait", "screenshot", "path"}
BLOCKED_PATTERNS = ["import os", "subprocess", "socket", "requests.", "http://", "https://"]


def validate_browser_steps(raw: str) -> List[Dict[str, Any]]:
    steps = json.loads(raw)
    if not isinstance(steps, list):
        raise ValueError("Browser plan must be a list")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each browser step must be an object")
        extra = set(step.keys()) - ALLOWED_BROWSER_KEYS
        if extra:
            raise ValueError(f"Disallowed browser step keys: {sorted(extra)}")
    return steps


def validate_python(code: str) -> None:
    lowered = code.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lowered:
            raise ValueError(f"Blocked code pattern detected: {pattern}")
