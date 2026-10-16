"""Tool-name sanitising for the ChatGPT/Codex Responses backend.

The backend requires function names to match ``^[a-zA-Z0-9_-]+$`` (max 64
chars), while clients such as the Letta App Server advertise host tools with
dots (``canvas.list``, ``canvas.get_scene``). Anthropic accepts those, the
ChatGPT backend rejects the whole request with a 400.

``ToolNameMap`` gives every invalid name a deterministic, collision-free
upstream alias for one request and maps it back on the way down. Valid names
are never touched, so requests without offending names are a no-op.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, Optional

VALID_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_TOOL_NAME_LEN = 64
_INVALID_CHAR = re.compile(r"[^a-zA-Z0-9_-]")


def _short_hash(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]


class ToolNameMap:
    """Per-request mapping between client tool names and upstream aliases."""

    def __init__(self, names: Iterable[str] = ()):
        self._up: Dict[str, str] = {}
        self._down: Dict[str, str] = {}
        self._used: set = set()
        names = [n for n in names if isinstance(n, str) and n]
        # Valid names keep themselves; reserve them first so an alias can never
        # shadow a real tool.
        for name in names:
            if VALID_TOOL_NAME.match(name) and len(name) <= MAX_TOOL_NAME_LEN:
                self._used.add(name)
        for name in names:
            self.up(name)

    @property
    def is_identity(self) -> bool:
        return not self._up

    def up(self, name: Any) -> Any:
        """Client name -> upstream name (registers a new alias if needed)."""
        if not isinstance(name, str) or not name:
            return name
        if VALID_TOOL_NAME.match(name) and len(name) <= MAX_TOOL_NAME_LEN:
            self._used.add(name)
            return name
        if name in self._up:
            return self._up[name]
        alias = _INVALID_CHAR.sub("__", name)
        if len(alias) > MAX_TOOL_NAME_LEN or alias in self._used:
            suffix = f"_{_short_hash(name)}"
            alias = alias[: MAX_TOOL_NAME_LEN - len(suffix)] + suffix
        while alias in self._used:  # vanishingly unlikely; stay deterministic
            suffix = f"_{_short_hash(alias)}"
            alias = alias[: MAX_TOOL_NAME_LEN - len(suffix)] + suffix
        self._used.add(alias)
        self._up[name] = alias
        self._down[alias] = name
        return alias

    def aliases(self) -> Dict[str, str]:
        return dict(self._up)

    def down(self, name: Any) -> Any:
        """Upstream name -> client name (unknown names pass through)."""
        if isinstance(name, str):
            return self._down.get(name, name)
        return name


# ---------------------------------------------------------------------------
# Responses-shaped payloads (both the chat path, after conversion, and the
# native /v1/responses path go through these)
# ---------------------------------------------------------------------------

def _tool_name_holder(tool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(tool, dict) or tool.get("type", "function") != "function":
        return None
    if isinstance(tool.get("function"), dict):
        return tool["function"]
    return tool


def _map_tool_choice(choice: Any, fn) -> Any:
    if not isinstance(choice, dict) or choice.get("type") != "function":
        return choice
    choice = dict(choice)
    if "name" in choice:
        choice["name"] = fn(choice["name"])
    if isinstance(choice.get("function"), dict):
        choice["function"] = {**choice["function"], "name": fn(choice["function"].get("name"))}
    return choice


def _map_tools(tools: Any, fn) -> Any:
    if not isinstance(tools, list):
        return tools
    out = []
    for tool in tools:
        holder = _tool_name_holder(tool)
        if holder is None or "name" not in holder:
            out.append(tool)
        elif holder is tool:
            out.append({**tool, "name": fn(tool["name"])})
        else:
            out.append({**tool, "function": {**holder, "name": fn(holder["name"])}})
    return out


def _map_function_call_item(item: Any, fn) -> Any:
    if isinstance(item, dict) and item.get("type") == "function_call" and "name" in item:
        return {**item, "name": fn(item["name"])}
    return item


def sanitize_responses_payload(payload: Dict[str, Any]) -> ToolNameMap:
    """Rewrite tool names in a Responses payload in place; return the map.

    Covers tools[], tool_choice and function_call items in input (earlier
    turns). function_call_output items reference calls by call_id only, so
    they need no change.
    """
    names = []
    for tool in payload.get("tools") or []:
        holder = _tool_name_holder(tool)
        if holder is not None:
            names.append(holder.get("name"))
    name_map = ToolNameMap(names)
    if "tools" in payload:
        payload["tools"] = _map_tools(payload["tools"], name_map.up)
    if "tool_choice" in payload:
        payload["tool_choice"] = _map_tool_choice(payload["tool_choice"], name_map.up)
    if isinstance(payload.get("input"), list):
        payload["input"] = [_map_function_call_item(item, name_map.up) for item in payload["input"]]
    return name_map


def restore_response_object(response: Any, name_map: ToolNameMap) -> Any:
    """Map names back in a Responses `response` object (output/tools/tool_choice)."""
    if not isinstance(response, dict) or name_map.is_identity:
        return response
    if isinstance(response.get("output"), list):
        response["output"] = [_map_function_call_item(i, name_map.down) for i in response["output"]]
    if "tools" in response:
        response["tools"] = _map_tools(response["tools"], name_map.down)
    if "tool_choice" in response:
        response["tool_choice"] = _map_tool_choice(response["tool_choice"], name_map.down)
    return response


def restore_responses_event(event: Any, name_map: ToolNameMap) -> Any:
    """Map names back in one Responses SSE event (item and embedded response)."""
    if not isinstance(event, dict) or name_map.is_identity:
        return event
    if "item" in event:
        event["item"] = _map_function_call_item(event["item"], name_map.down)
    if "response" in event:
        restore_response_object(event["response"], name_map)
    return event
