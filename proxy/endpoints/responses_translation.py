"""Translation helpers for the OpenAI Responses API endpoint (/v1/responses).

Two directions are covered:

* Responses request -> chat-completions request, so models that are not served
  by the ChatGPT/Codex backend (Anthropic, custom providers) can reuse the
  existing chat-completions pipeline.
* chat-completions output (a completion object or an SSE chunk stream) ->
  a Responses object / Responses SSE event stream, mirroring the event shapes
  the ChatGPT backend emits (response.created ... response.completed) so
  gateways such as LiteLLM consume both paths the same way.

Also folds a native Responses SSE stream into one Responses object, because the
Codex backend only serves streaming requests.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple


class ResponsesInputError(ValueError):
    """The client's Responses `input` cannot be interpreted."""


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------

_TEXT_PART_FOR_ROLE = {"assistant": "output_text"}


def _text_part(role: str, text: str) -> Dict[str, Any]:
    return {"type": _TEXT_PART_FOR_ROLE.get(role, "input_text"), "text": text}


def normalize_responses_input(value: Any) -> List[Dict[str, Any]]:
    """Return Responses `input` as the list form the Codex backend requires.

    Accepts the string shorthand, and messages either in the easy form
    (``{"role", "content": "text"}``) or the explicit item form
    (``{"type": "message", "role", "content": [parts]}``). Non-message items
    (function_call, function_call_output, reasoning, ...) pass through.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [{"role": "user", "content": [_text_part("user", value)]}]
    if not isinstance(value, list):
        raise ResponsesInputError("'input' must be a string or a list of input items")

    items: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            items.append({"role": "user", "content": [_text_part("user", item)]})
            continue
        if not isinstance(item, dict):
            raise ResponsesInputError("every 'input' item must be an object or a string")
        is_message = item.get("type") in (None, "message") and "role" in item
        if is_message and isinstance(item.get("content"), str):
            item = {**item, "content": [_text_part(item["role"], item["content"])]}
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Responses request -> chat-completions request
# ---------------------------------------------------------------------------

def _content_text(content: Any) -> str:
    """Concatenate the text of a Responses content value (string or parts)."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else json.dumps(content)
    texts = []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "".join(texts)


def _user_content_to_chat(content: Any) -> Any:
    """Map user content parts to chat content (string when it is all text)."""
    if isinstance(content, str) or not isinstance(content, list):
        return _content_text(content)
    parts: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        kind = part.get("type")
        if kind in ("input_text", "output_text", "text"):
            parts.append({"type": "text", "text": part.get("text", "")})
        elif kind == "input_image":
            url = part.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if isinstance(url, str) and url:
                image = {"url": url}
                if part.get("detail"):
                    image["detail"] = part["detail"]
                parts.append({"type": "image_url", "image_url": image})
    if all(p["type"] == "text" for p in parts):
        return "".join(p["text"] for p in parts)
    return parts


def _append_tool_call(messages: List[Dict[str, Any]], item: Dict[str, Any]) -> None:
    arguments = item.get("arguments", "")
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    call = {
        "id": item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": item.get("name", ""), "arguments": arguments},
    }
    last = messages[-1] if messages else None
    if last and last.get("role") == "assistant":
        last.setdefault("tool_calls", []).append(call)
    else:
        messages.append({"role": "assistant", "content": None, "tool_calls": [call]})


def _append_assistant_text(messages: List[Dict[str, Any]], text: str) -> None:
    """Add an assistant `message` item, keeping it ahead of the turn's tool calls.

    LiteLLM's Anthropic -> Responses adapter emits an assistant turn
    ``[text, tool_use]`` as the ``function_call`` items first and the
    ``message`` item after them. Appending that message as a new assistant
    message yields Anthropic content ``[tool_use, text]``; as the last
    assistant turn, models without prefill support (Opus/Sonnet 5.5) reject it
    with "does not support assistant message prefill" (letta-mobile-fosvg).
    While the tool-call turn is still open (no tool output or user message
    since), the text belongs to that turn, so fold it into its `content`,
    which the Anthropic converter renders before the tool_use blocks.
    """
    last = messages[-1] if messages else None
    if not (last and last.get("role") == "assistant" and last.get("tool_calls")):
        messages.append({"role": "assistant", "content": text})
        return
    if not text:
        return
    existing = last.get("content")
    if not existing:
        last["content"] = text
        return
    parts = existing if isinstance(existing, list) else [{"type": "text", "text": existing}]
    last["content"] = parts + [{"type": "text", "text": text}]


def _tool_output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        return _content_text(output)
    return json.dumps(output)


def responses_input_to_messages(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for item in items:
        kind = item.get("type")
        if kind in (None, "message") and "role" in item:
            role = item["role"]
            if role in ("system", "developer"):
                messages.append({"role": "system", "content": _content_text(item.get("content"))})
            elif role == "assistant":
                _append_assistant_text(messages, _content_text(item.get("content")))
            else:
                messages.append({"role": "user", "content": _user_content_to_chat(item.get("content"))})
        elif kind == "function_call":
            _append_tool_call(messages, item)
        elif kind == "function_call_output":
            messages.append({
                "role": "tool",
                "tool_call_id": item.get("call_id", ""),
                "content": _tool_output_text(item.get("output", "")),
            })
        # reasoning / item_reference / hosted-tool items have no chat
        # equivalent; Anthropic thinking is re-attached by the proxy's own
        # thinking cache, so dropping them is safe.
    return messages


def _tools_to_chat(tools: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            continue
        if isinstance(tool.get("function"), dict):  # already chat-shaped
            out.append({"type": "function", "function": tool["function"]})
            continue
        function: Dict[str, Any] = {"name": tool.get("name", "")}
        if tool.get("description"):
            function["description"] = tool["description"]
        function["parameters"] = tool.get("parameters") or {"type": "object", "properties": {}}
        out.append({"type": "function", "function": function})
    return out


def _tool_choice_to_chat(choice: Any) -> Any:
    if isinstance(choice, dict) and choice.get("type") == "function" and "name" in choice:
        return {"type": "function", "function": {"name": choice["name"]}}
    return choice


def responses_to_chat_request(payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Translate a Responses request body into a chat-completions body."""
    messages: List[Dict[str, Any]] = []
    instructions = payload.get("instructions")
    if isinstance(instructions, str) and instructions.strip():
        messages.append({"role": "system", "content": instructions})
    messages.extend(responses_input_to_messages(normalize_responses_input(payload.get("input"))))

    chat: Dict[str, Any] = {"model": model, "messages": messages, "stream": bool(payload.get("stream"))}
    if chat["stream"]:
        chat["stream_options"] = {"include_usage": True}
    tools = _tools_to_chat(payload.get("tools"))
    if tools:
        chat["tools"] = tools
        if payload.get("tool_choice") is not None:
            chat["tool_choice"] = _tool_choice_to_chat(payload["tool_choice"])
    if payload.get("max_output_tokens"):
        chat["max_tokens"] = payload["max_output_tokens"]
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            chat[key] = payload[key]
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("effort"):
        chat["reasoning_effort"] = reasoning["effort"]
    return chat


# ---------------------------------------------------------------------------
# chat-completions output -> Responses object / events
# ---------------------------------------------------------------------------

def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def chat_usage_to_responses(usage: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not usage:
        return None
    input_tokens = usage.get("prompt_tokens", 0) or 0
    output_tokens = usage.get("completion_tokens", 0) or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": output_tokens,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": usage.get("total_tokens") or input_tokens + output_tokens,
    }


def _message_item(item_id: str, text: str, status: str = "completed") -> Dict[str, Any]:
    content = [] if status == "in_progress" else [{"type": "output_text", "annotations": [], "text": text}]
    return {"id": item_id, "type": "message", "status": status, "role": "assistant", "content": content}


def _reasoning_item(item_id: str, text: str, done: bool = True) -> Dict[str, Any]:
    summary = [{"type": "summary_text", "text": text}] if done else []
    return {"id": item_id, "type": "reasoning", "summary": summary}


def _function_call_item(item_id: str, call_id: str, name: str, arguments: str, status: str = "completed") -> Dict[str, Any]:
    return {
        "id": item_id, "type": "function_call", "status": status,
        "arguments": arguments, "call_id": call_id, "name": name,
    }


def response_envelope(
    response_id: str,
    model: str,
    created_at: int,
    request: Dict[str, Any],
    status: str,
    output: List[Dict[str, Any]],
    usage: Optional[Dict[str, Any]] = None,
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    incomplete = None
    if status == "completed" and finish_reason == "length":
        status, incomplete = "incomplete", {"reason": "max_output_tokens"}
    return {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": status,
        "error": None,
        "incomplete_details": incomplete,
        "instructions": request.get("instructions"),
        "max_output_tokens": request.get("max_output_tokens"),
        "model": model,
        "output": output,
        "parallel_tool_calls": request.get("parallel_tool_calls", True),
        "previous_response_id": request.get("previous_response_id"),
        "reasoning": request.get("reasoning"),
        "store": bool(request.get("store", False)),
        "temperature": request.get("temperature"),
        "tool_choice": request.get("tool_choice", "auto"),
        "tools": request.get("tools") or [],
        "top_p": request.get("top_p"),
        "usage": usage,
        "metadata": request.get("metadata") or {},
    }


def chat_completion_to_response(
    completion: Dict[str, Any],
    request: Dict[str, Any],
    model: str,
    response_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a chat.completion object into a Responses `response` object."""
    choice = (completion.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    output: List[Dict[str, Any]] = []
    if message.get("reasoning_content"):
        output.append(_reasoning_item(_new_id("rs"), message["reasoning_content"]))
    content = message.get("content")
    if isinstance(content, list):
        content = _content_text(content)
    if content:
        output.append(_message_item(_new_id("msg"), content))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        output.append(_function_call_item(
            _new_id("fc"),
            call.get("id") or _new_id("call"),
            function.get("name", ""),
            function.get("arguments") or "",
        ))
    return response_envelope(
        response_id or _new_id("resp"),
        model,
        int(completion.get("created") or time.time()),
        request,
        "completed",
        output,
        chat_usage_to_responses(completion.get("usage")),
        choice.get("finish_reason"),
    )


def sse_event(event: Dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


class ChatToResponsesStream:
    """Stateful translator: chat.completion.chunk dicts -> Responses SSE events.

    Emits the same event vocabulary as the ChatGPT backend: response.created,
    response.in_progress, response.output_item.added/done,
    response.content_part.added/done, response.output_text.delta/done,
    response.reasoning_summary_* for thinking, response.function_call_arguments
    .delta/done, then response.completed (or response.failed) with usage.
    """

    def __init__(self, request: Dict[str, Any], model: str, response_id: Optional[str] = None):
        self.request = request
        self.model = model
        self.response_id = response_id or _new_id("resp")
        self.created_at = int(time.time())
        self.seq = 0
        self.output: List[Optional[Dict[str, Any]]] = []  # finished items by output_index
        self.usage: Optional[Dict[str, Any]] = None
        self.finish_reason: Optional[str] = None
        self._text: Optional[Dict[str, Any]] = None  # open message / reasoning item
        self._tools: Dict[int, Dict[str, Any]] = {}  # chat tool index -> open call

    # -- helpers ----------------------------------------------------------
    def _emit(self, event: Dict[str, Any]) -> str:
        event["sequence_number"] = self.seq
        self.seq += 1
        return sse_event(event)

    def _envelope(self, status: str) -> Dict[str, Any]:
        output = [item for item in self.output if item is not None]
        return response_envelope(
            self.response_id, self.model, self.created_at, self.request, status,
            output if status != "in_progress" else [], self.usage, self.finish_reason,
        )

    def _reserve_index(self) -> int:
        self.output.append(None)
        return len(self.output) - 1

    def start(self) -> List[str]:
        return [
            self._emit({"type": "response.created", "response": self._envelope("in_progress")}),
            self._emit({"type": "response.in_progress", "response": self._envelope("in_progress")}),
        ]

    # -- open/close text-like items ----------------------------------------
    def _open_text(self, kind: str) -> List[str]:
        events = self._close_text() if self._text and self._text["kind"] != kind else []
        if self._text:
            return events
        events += self._close_tools()
        index = self._reserve_index()
        if kind == "message":
            item_id = _new_id("msg")
            events.append(self._emit({"type": "response.output_item.added", "output_index": index,
                                      "item": _message_item(item_id, "", status="in_progress")}))
            events.append(self._emit({"type": "response.content_part.added", "item_id": item_id,
                                      "output_index": index, "content_index": 0,
                                      "part": {"type": "output_text", "annotations": [], "text": ""}}))
        else:
            item_id = _new_id("rs")
            events.append(self._emit({"type": "response.output_item.added", "output_index": index,
                                      "item": _reasoning_item(item_id, "", done=False)}))
            events.append(self._emit({"type": "response.reasoning_summary_part.added", "item_id": item_id,
                                      "output_index": index, "summary_index": 0,
                                      "part": {"type": "summary_text", "text": ""}}))
        self._text = {"kind": kind, "id": item_id, "index": index, "parts": []}
        return events

    def _close_text(self) -> List[str]:
        if not self._text:
            return []
        t, self._text = self._text, None
        text = "".join(t["parts"])
        if t["kind"] == "message":
            part = {"type": "output_text", "annotations": [], "text": text}
            item = _message_item(t["id"], text)
            events = [
                self._emit({"type": "response.output_text.done", "item_id": t["id"], "output_index": t["index"],
                            "content_index": 0, "text": text}),
                self._emit({"type": "response.content_part.done", "item_id": t["id"], "output_index": t["index"],
                            "content_index": 0, "part": part}),
            ]
        else:
            item = _reasoning_item(t["id"], text)
            events = [
                self._emit({"type": "response.reasoning_summary_text.done", "item_id": t["id"],
                            "output_index": t["index"], "summary_index": 0, "text": text}),
                self._emit({"type": "response.reasoning_summary_part.done", "item_id": t["id"],
                            "output_index": t["index"], "summary_index": 0,
                            "part": {"type": "summary_text", "text": text}}),
            ]
        self.output[t["index"]] = item
        events.append(self._emit({"type": "response.output_item.done", "output_index": t["index"], "item": item}))
        return events

    # -- tool calls ---------------------------------------------------------
    def _tool_delta(self, delta_call: Dict[str, Any]) -> List[str]:
        events: List[str] = []
        chat_index = int(delta_call.get("index", 0))
        function = delta_call.get("function") or {}
        call = self._tools.get(chat_index)
        if call is None:
            events += self._close_text()
            index = self._reserve_index()
            call = {
                "id": _new_id("fc"), "index": index,
                "call_id": delta_call.get("id") or _new_id("call"),
                "name": function.get("name") or "", "arguments": "",
            }
            self._tools[chat_index] = call
            events.append(self._emit({"type": "response.output_item.added", "output_index": index,
                                      "item": _function_call_item(call["id"], call["call_id"], call["name"], "",
                                                                  status="in_progress")}))
        elif function.get("name") and not call["name"]:
            call["name"] = function["name"]
        arguments = function.get("arguments")
        if arguments:
            call["arguments"] += arguments
            events.append(self._emit({"type": "response.function_call_arguments.delta", "item_id": call["id"],
                                      "output_index": call["index"], "delta": arguments}))
        return events

    def _close_tools(self) -> List[str]:
        events: List[str] = []
        for chat_index in sorted(self._tools, key=lambda k: self._tools[k]["index"]):
            call = self._tools[chat_index]
            item = _function_call_item(call["id"], call["call_id"], call["name"], call["arguments"])
            self.output[call["index"]] = item
            events.append(self._emit({"type": "response.function_call_arguments.done", "item_id": call["id"],
                                      "output_index": call["index"], "arguments": call["arguments"]}))
            events.append(self._emit({"type": "response.output_item.done", "output_index": call["index"],
                                      "item": item}))
        self._tools = {}
        return events

    # -- public -------------------------------------------------------------
    def feed(self, chunk: Dict[str, Any]) -> List[str]:
        events: List[str] = []
        if chunk.get("usage"):
            self.usage = chat_usage_to_responses(chunk["usage"])
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("reasoning_content"):
                events += self._open_text("reasoning")
                self._text["parts"].append(delta["reasoning_content"])
                events.append(self._emit({"type": "response.reasoning_summary_text.delta",
                                          "item_id": self._text["id"], "output_index": self._text["index"],
                                          "summary_index": 0, "delta": delta["reasoning_content"]}))
            if delta.get("content"):
                events += self._open_text("message")
                self._text["parts"].append(delta["content"])
                events.append(self._emit({"type": "response.output_text.delta", "item_id": self._text["id"],
                                          "output_index": self._text["index"], "content_index": 0,
                                          "delta": delta["content"], "logprobs": []}))
            for delta_call in delta.get("tool_calls") or []:
                events += self._tool_delta(delta_call)
            if choice.get("finish_reason"):
                self.finish_reason = choice["finish_reason"]
        return events

    def finish(self) -> List[str]:
        events = self._close_text() + self._close_tools()
        events.append(self._emit({"type": "response.completed", "response": self._envelope("completed")}))
        return events

    def fail(self, message: str, code: str = "server_error") -> List[str]:
        events = self._close_text() + self._close_tools()
        response = self._envelope("failed")
        response["error"] = {"code": code, "message": message}
        events.append(self._emit({"type": "response.failed", "response": response}))
        return events


# ---------------------------------------------------------------------------
# SSE parsing
# ---------------------------------------------------------------------------

async def iter_sse_events(chunks: AsyncIterator[Any]) -> AsyncIterator[Tuple[Optional[str], Any]]:
    """Yield (event_name, parsed_data) from an SSE byte/str stream.

    Handles chunks that carry several events or partial lines. `event:` names
    apply to the next `data:` line. Non-JSON data (e.g. [DONE]) is yielded as a
    string.
    """
    buffer = ""
    event_name: Optional[str] = None
    async for chunk in chunks:
        buffer += chunk.decode("utf-8", "replace") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                event_name = None
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
                try:
                    parsed: Any = json.loads(data)
                except json.JSONDecodeError:
                    parsed = data
                yield event_name, parsed
    line = buffer.strip()
    if line.startswith("data:"):
        data = line[len("data:"):].strip()
        try:
            yield event_name, json.loads(data)
        except json.JSONDecodeError:
            yield event_name, data


def stream_error_of(event_name: Optional[str], data: Any) -> Optional[Dict[str, Any]]:
    """Return {"message", "type", "status"} if an SSE event is an error, else None."""
    if event_name != "error" and not (isinstance(data, dict) and "error" in data):
        return None
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        message = error.get("message") or json.dumps(error)
        kind = error.get("type") or "api_error"
        upstream = error.get("upstream_body") or error.get("detail")
        if upstream:
            message = f"{message}: {upstream_error_message(upstream)}"
    else:
        message, kind = str(error), "api_error"
    return {"message": message, "type": kind, "status": status_for_error(kind, message)}


_ERROR_TYPE_STATUS = {
    "invalid_request_error": 400,
    "authentication_error": 401,
    "permission_error": 403,
    "not_found_error": 404,
    "request_too_large": 413,
    "rate_limit_error": 429,
    "overloaded_error": 503,
}


def status_for_error(kind: Optional[str], message: str = "") -> int:
    """Pick the client status for an upstream error seen inside a stream."""
    match = re.search(r"\berror:? (\d{3})\b", message or "")
    if match and 400 <= int(match.group(1)) < 500:
        return int(match.group(1))
    return _ERROR_TYPE_STATUS.get(kind or "", 502)


def upstream_error_message(body: Any) -> str:
    """Extract a human message from an upstream error body (dict or JSON text)."""
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return body.strip()
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            return str(body["error"].get("message") or body["error"])
        if body.get("error"):
            return str(body["error"])
        if body.get("detail"):
            detail = body["detail"]
            return detail if isinstance(detail, str) else upstream_error_message(detail)
        if body.get("message"):
            return str(body["message"])
    return json.dumps(body)



# ---------------------------------------------------------------------------
# Native Responses SSE -> one Responses object
# ---------------------------------------------------------------------------

class UpstreamResponseFailed(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


async def fold_responses_sse(chunks: AsyncIterator[Any]) -> Dict[str, Any]:
    """Consume a Responses SSE stream and return the final `response` object.

    The Codex backend's response.completed carries an empty `output`, so output
    items are rebuilt from response.output_item.done events.
    """
    items: Dict[int, Dict[str, Any]] = {}
    final: Optional[Dict[str, Any]] = None
    async for event_name, data in iter_sse_events(chunks):
        if not isinstance(data, dict):
            continue
        kind = data.get("type") or event_name
        if kind == "response.output_item.done":
            items[int(data.get("output_index", len(items)))] = data.get("item") or {}
        elif kind in ("response.completed", "response.incomplete"):
            final = data.get("response") or {}
        elif kind == "response.failed":
            error = (data.get("response") or {}).get("error") or {}
            raise UpstreamResponseFailed(error.get("message") or "upstream response failed")
        elif kind == "error" or "error" in data:
            error = data.get("error", data)
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise UpstreamResponseFailed(message or "upstream stream error")
    if final is None:
        raise UpstreamResponseFailed("upstream stream ended without response.completed")
    if not final.get("output") and items:
        final["output"] = [items[i] for i in sorted(items)]
    return final
