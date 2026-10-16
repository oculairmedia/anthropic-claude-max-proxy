"""Tool names outside ^[a-zA-Z0-9_-]+$ (Letta's canvas.* host tools) are aliased
for the ChatGPT backend and mapped back on every downstream path."""
import asyncio
import json

import httpx

from conftest import _sse
from providers import chatgpt_provider
from providers.chatgpt_provider import ChatGPTProvider
from providers.tool_names import VALID_TOOL_NAME, ToolNameMap, sanitize_responses_payload


def _fn_call_stream(name, call_id="call_1", arguments="{}"):
    item = {"id": "fc_1", "type": "function_call", "status": "completed",
            "arguments": arguments, "call_id": call_id, "name": name}
    return "".join([
        _sse({"type": "response.created", "response": {"id": "resp_1", "output": [],
              "tools": [{"type": "function", "name": name}]}}, "response.created"),
        _sse({"type": "response.output_item.added", "output_index": 0,
              "item": {**item, "status": "in_progress", "arguments": ""}}, "response.output_item.added"),
        _sse({"type": "response.function_call_arguments.done", "output_index": 0, "item_id": "fc_1",
              "arguments": arguments}, "response.function_call_arguments.done"),
        _sse({"type": "response.output_item.done", "output_index": 0, "item": item}, "response.output_item.done"),
        _sse({"type": "response.completed", "response": {"id": "resp_1", "object": "response", "status": "completed",
              "output": [], "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
             "response.completed"),
    ])


CANVAS_TOOLS = [
    {"type": "function", "name": "canvas.list", "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "canvas.get_scene", "parameters": {"type": "object", "properties": {}}},
    {"type": "function", "name": "send_message", "parameters": {"type": "object", "properties": {}}},
]


# --- mapping ---------------------------------------------------------------------

def test_map_is_deterministic_and_reversible():
    m = ToolNameMap(["canvas.list", "canvas.get_scene", "send_message"])
    assert m.up("canvas.list") == "canvas__list"
    assert m.up("canvas.get_scene") == "canvas__get_scene"
    assert m.up("send_message") == "send_message"
    assert m.down("canvas__list") == "canvas.list"
    assert m.down("send_message") == "send_message"
    assert ToolNameMap(["canvas.list"]).up("canvas.list") == m.up("canvas.list")


def test_alias_never_collides_with_a_real_tool():
    m = ToolNameMap(["canvas.list", "canvas__list"])
    alias = m.up("canvas.list")
    assert alias != "canvas__list" and VALID_TOOL_NAME.match(alias)
    assert m.down(alias) == "canvas.list"
    assert m.down("canvas__list") == "canvas__list"


def test_long_names_fit_the_limit():
    name = "ns." + "x" * 80
    alias = ToolNameMap([name]).up(name)
    assert len(alias) <= 64 and VALID_TOOL_NAME.match(alias)


def test_valid_names_are_a_noop():
    payload = {"tools": [{"type": "function", "name": "send_message"}], "tool_choice": "auto",
               "input": [{"type": "function_call", "call_id": "c", "name": "send_message", "arguments": "{}"}]}
    before = json.loads(json.dumps(payload))
    m = sanitize_responses_payload(payload)
    assert m.is_identity and payload == before


def test_payload_tools_choice_and_history_are_sanitized():
    payload = {
        "tools": CANVAS_TOOLS,
        "tool_choice": {"type": "function", "name": "canvas.list"},
        "input": [
            {"type": "function_call", "call_id": "c1", "name": "canvas.get_scene", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "ok"},
        ],
    }
    sanitize_responses_payload(payload)
    assert all(VALID_TOOL_NAME.match(t["name"]) for t in payload["tools"])
    assert payload["tool_choice"] == {"type": "function", "name": "canvas__list"}
    assert payload["input"][0]["name"] == "canvas__get_scene"
    assert payload["input"][1] == {"type": "function_call_output", "call_id": "c1", "output": "ok"}


# --- /v1/responses (native ChatGPT path) -------------------------------------------

def test_responses_stream_sanitizes_up_and_restores_down(client, chatgpt_upstream):
    chatgpt_upstream["body"] = _fn_call_stream("canvas__list")
    resp = client.post("/v1/responses", json={
        "model": "gpt-5.6-sol", "input": "list canvases", "stream": True,
        "tools": CANVAS_TOOLS, "tool_choice": {"type": "function", "name": "canvas.list"},
    })
    assert resp.status_code == 200, resp.text
    sent = chatgpt_upstream["payload"]
    assert [t["name"] for t in sent["tools"]] == ["canvas__list", "canvas__get_scene", "send_message"]
    assert sent["tool_choice"] == {"type": "function", "name": "canvas__list"}

    events = [json.loads(l[5:]) for l in resp.text.splitlines() if l.startswith("data:")]
    by_type = {e["type"]: e for e in events}
    assert by_type["response.output_item.added"]["item"]["name"] == "canvas.list"
    assert by_type["response.output_item.done"]["item"]["name"] == "canvas.list"
    assert by_type["response.created"]["response"]["tools"][0]["name"] == "canvas.list"
    assert "canvas__list" not in resp.text


def test_responses_non_stream_restores_names(client, chatgpt_upstream):
    chatgpt_upstream["body"] = _fn_call_stream("canvas__get_scene")
    resp = client.post("/v1/responses", json={"model": "gpt-5.6-sol", "input": "x", "tools": CANVAS_TOOLS})
    assert resp.status_code == 200, resp.text
    assert resp.json()["output"][0]["name"] == "canvas.get_scene"


def test_responses_without_invalid_names_is_passthrough(client, chatgpt_upstream):
    chatgpt_upstream["body"] = _fn_call_stream("send_message")
    tools = [CANVAS_TOOLS[2]]
    resp = client.post("/v1/responses", json={"model": "gpt-5.6-sol", "input": "x", "stream": True, "tools": tools})
    assert chatgpt_upstream["payload"]["tools"] == tools
    assert resp.text == chatgpt_upstream["body"]  # byte-for-byte passthrough


# --- /v1/chat/completions ChatGPT path (ChatGPTProvider) -----------------------------

def test_chat_path_sanitizes_tools_history_and_choice_and_restores_stream(monkeypatch):
    captured = {}
    real_client = httpx.AsyncClient

    def handler(request):
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=_fn_call_stream("canvas__list", call_id="call_9").encode(),
                              headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(chatgpt_provider.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))

    class Creds:
        async def get_auth_credentials_async(self):
            return "token", "account"

    request = {
        "model": "gpt-5.6-sol",
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_0", "type": "function", "function": {"name": "canvas.get_scene", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_0", "content": "scene"},
        ],
        "tools": [{"type": "function", "function": {"name": t["name"], "parameters": t["parameters"]}} for t in CANVAS_TOOLS],
        "tool_choice": {"type": "function", "function": {"name": "canvas.list"}},
    }

    async def run():
        return [c async for c in ChatGPTProvider(oauth_manager=Creds()).stream_response(request, "t1")]

    chunks = asyncio.run(run())
    sent = captured["payload"]
    assert all(VALID_TOOL_NAME.match(t["name"]) for t in sent["tools"])
    assert sent["tool_choice"] == {"type": "function", "name": "canvas__list"}
    calls = [i for i in sent["input"] if i.get("type") == "function_call"]
    assert calls[0]["name"] == "canvas__get_scene" and calls[0]["call_id"] == "call_0"
    outputs = [i for i in sent["input"] if i.get("type") == "function_call_output"]
    assert outputs[0]["call_id"] == "call_0"

    tool_chunks = [json.loads(c[6:]) for c in chunks if '"tool_calls"' in c]
    fn = tool_chunks[0]["choices"][0]["delta"]["tool_calls"][0]
    assert fn["function"]["name"] == "canvas.list" and fn["id"] == "call_9"
