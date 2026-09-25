"""Fold an OpenAI-format SSE stream into one chat.completion object.

The ChatGPT Responses backend only serves streaming requests ("Stream must be set
to true"), while clients such as the Letta App Server sometimes ask for a
non-streaming completion. Rather than forwarding that request and failing, the
endpoint streams upstream and aggregates the chunks here.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional


class UpstreamStreamError(Exception):
    """The upstream stream reported an error event instead of content."""


def _parse_sse_data(chunk: str) -> Optional[str]:
    """Return the payload of a single `data:` SSE chunk, or None if it has none."""
    for line in chunk.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return line[len("data:"):].strip()
    return None


def _merge_tool_call(slots: Dict[int, Dict[str, Any]], delta_call: Dict[str, Any]) -> None:
    index = int(delta_call.get("index", 0))
    slot = slots.setdefault(
        index,
        {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
    )
    if delta_call.get("id"):
        slot["id"] = delta_call["id"]
    if delta_call.get("type"):
        slot["type"] = delta_call["type"]
    function = delta_call.get("function") or {}
    if function.get("name"):
        slot["function"]["name"] = function["name"]
    if function.get("arguments"):
        slot["function"]["arguments"] += function["arguments"]


def _apply_delta(state: Dict[str, Any], choice: Dict[str, Any]) -> None:
    delta = choice.get("delta") or {}
    if delta.get("role"):
        state["role"] = delta["role"]
    if delta.get("content"):
        state["content"].append(delta["content"])
    if delta.get("reasoning_content"):
        state["reasoning"].append(delta["reasoning_content"])
    for delta_call in delta.get("tool_calls") or []:
        _merge_tool_call(state["tool_calls"], delta_call)
    if choice.get("finish_reason"):
        state["finish_reason"] = choice["finish_reason"]


def _apply_event(state: Dict[str, Any], event: Dict[str, Any]) -> None:
    if "error" in event:
        error = event["error"]
        message = error.get("message") if isinstance(error, dict) else str(error)
        upstream = error.get("upstream_body") if isinstance(error, dict) else None
        if upstream:
            message = f"{message}: {upstream}"
        raise UpstreamStreamError(message or "upstream stream error")
    state["id"] = state["id"] or event.get("id")
    state["model"] = state["model"] or event.get("model")
    state["created"] = state["created"] or event.get("created")
    if event.get("usage"):
        state["usage"] = event["usage"]
    for choice in event.get("choices") or []:
        _apply_delta(state, choice)


def _completion_from_state(state: Dict[str, Any], fallback_model: str) -> Dict[str, Any]:
    message: Dict[str, Any] = {"role": state["role"], "content": "".join(state["content"]) or None}
    if state["reasoning"]:
        message["reasoning_content"] = "".join(state["reasoning"])
    tool_calls: List[Dict[str, Any]] = [state["tool_calls"][i] for i in sorted(state["tool_calls"])]
    if tool_calls:
        message["tool_calls"] = tool_calls
    finish_reason = state["finish_reason"] or ("tool_calls" if tool_calls else "stop")
    completion: Dict[str, Any] = {
        "id": state["id"] or f"chatcmpl-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": state["created"] or int(time.time()),
        "model": state["model"] or fallback_model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }
    if state["usage"]:
        completion["usage"] = state["usage"]
    return completion


async def aggregate_openai_sse(chunks: AsyncIterator[str], fallback_model: str) -> Dict[str, Any]:
    """Consume OpenAI-format SSE chunks and return a single chat.completion dict.

    Raises UpstreamStreamError if the stream carries an error event.
    """
    state: Dict[str, Any] = {
        "id": None, "model": None, "created": None, "role": "assistant",
        "content": [], "reasoning": [], "tool_calls": {}, "finish_reason": None, "usage": None,
    }
    async for chunk in chunks:
        data = _parse_sse_data(chunk)
        if data is None or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        _apply_event(state, event)
    return _completion_from_state(state, fallback_model)
