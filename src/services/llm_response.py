"""AgentCore Platform v1.0"""

# Shared LLM response handling.
#
# `BaseLLM.complete()` takes a message list and returns a dict
# (`shared/services/llm/base_llm.py`):
#     {"content": str, "tool_calls": list, "model": str, "usage": {...}}
# Passing a bare prompt string makes a real provider raise, and treating the dict
# result as text lets a non-str value reach downstream nodes and the S-3 output
# gate — where it either raises or silently bypasses the content scan.

from __future__ import annotations

from typing import Any


def build_llm_messages(prompt: str) -> list[dict[str, str]]:
    """Wrap a prompt in the canonical `BaseLLM.complete(messages: list)` shape."""
    return [{"role": "user", "content": prompt}]


def extract_llm_text(raw: Any) -> str:
    """Normalise a `BaseLLM.complete()` response to text.

    Canonical `complete()` returns `{"content": str, ...}`. A bare string is also
    accepted for backward compatibility with string-returning test fakes. Anything
    else (missing/non-str `content`, unexpected type) yields `""`, which the caller
    MUST treat as a failed completion — never as usable text.
    """
    if isinstance(raw, dict):
        content = raw.get("content", "")
        return content if isinstance(content, str) else ""
    if isinstance(raw, str):
        return raw
    return ""
