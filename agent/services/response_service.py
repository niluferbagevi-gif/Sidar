"""Response parsing helpers for Sidar agent orchestration."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_tool_call(raw: str) -> dict[str, Any]:
    """Normalize an LLM response into the legacy tool-call dictionary contract."""
    text = raw.strip() if isinstance(raw, str) else ""
    markdown_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if markdown_match:
        text = markdown_match.group(1).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"tool": "final_answer", "argument": raw}
    if not isinstance(data, dict):
        return {"tool": "final_answer", "argument": raw}
    data.setdefault("tool", "final_answer")
    return data
