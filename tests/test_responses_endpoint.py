"""Hermetic tests for /v1/responses routing, normalisation, bridging and errors.

Upstreams are mocked: the ChatGPT backend via an httpx.MockTransport, the
Anthropic side at the chat pipeline's make_anthropic_request /
create_openai_stream seams.
"""
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy.endpoints import openai_chat  # noqa: E402
from proxy.endpoints.responses_translation import (  # noqa: E402
    normalize_responses_input,
    responses_to_chat_request,
)


def _parse_events(text):
    events = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


# --- model resolution + input normalisation (ChatGPT path) -----------------

def test_sol_string_input_resolves_model_and_normalises_input(client, chatgpt_upstream):
    resp = client.post("/v1/responses", json={
        "model": "gpt-5.6-sol-reasoning-high", "input": "say hi", "stream": False,
        "max_output_tokens": 100, "previous_response_id": "resp_x", "store": True,
    })
    assert resp.status_code == 200, resp.text
    sent = chatgpt_upstream["payload"]
    assert sent["model"] == "gpt-5.6-sol"
    assert sent["reasoning"]["effort"] == "high"
    assert sent["input"] == [{"role": "user", "content": [{"type": "input_text", "text": "say hi"}]}]
    assert sent["stream"] is True and sent["store"] is False
    for unsupported in ("max_output_tokens", "previous_response_id"):
        assert unsupported not in sent
    body = resp.json()
    assert body["status"] == "completed"
    assert body["output"][0]["content"][0]["text"] == "Hi!"


def test_hidden_alias_and_explicit_effort(client, chatgpt_upstream):
    resp = client.post("/v1/responses", json={
        "model": "gpt-5.6-sol-xhigh", "input": [{"role": "user", "content": "hi"}],
        "reasoning": {"effort": "low"}, "stream": True,
    })
    assert resp.status_code == 200
    sent = chatgpt_upstream["payload"]
    assert sent["model"] == "gpt-5.6-sol"
    assert sent["reasoning"]["effort"] == "low"  # explicit client effort wins
    assert sent["input"][0]["content"] == [{"type": "input_text", "text": "hi"}]
    assert "response.completed" in resp.text


def test_unknown_model_is_400(client):
    resp = client.post("/v1/responses", json={"model": "no-such-model", "input": "hi"})
    assert resp.status_code == 400
    assert "Unknown model 'no-such-model'" in resp.json()["error"]["message"]


def test_upstream_400_is_returned_as_400(client, chatgpt_upstream):
    chatgpt_upstream["status"] = 400
    chatgpt_upstream["body"] = json.dumps({"detail": "Input must be a list"})
    for stream in (False, True):
        resp = client.post("/v1/responses", json={"model": "gpt-5.6-sol", "input": "hi", "stream": stream})
        assert resp.status_code == 400
        assert resp.json()["error"]["message"] == "Input must be a list"


def test_upstream_5xx_is_502(client, chatgpt_upstream):
    chatgpt_upstream["status"] = 503
    chatgpt_upstream["body"] = "overloaded"
    resp = client.post("/v1/responses", json={"model": "gpt-5.6-sol", "input": "hi"})
    assert resp.status_code == 502


# --- bridge to chat-completions (Anthropic) ----------------------------------

@pytest.fixture
def anthropic_token(monkeypatch):
    async def token():
        return "anthropic-token"
    monkeypatch.setattr(openai_chat.oauth_manager, "get_valid_token_async", token)


def test_opus5_bridges_to_chat_and_returns_response_object(client, anthropic_token, monkeypatch):
    seen = {}

    async def fake_anthropic(anthropic_request, access_token, beta_headers):
        seen["request"] = anthropic_request
        return httpx.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
            "content": [{"type": "text", "text": "Hello from Opus"},
                        {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"q": "x"}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 12, "output_tokens": 4},
        })

    monkeypatch.setattr(openai_chat, "make_anthropic_request", fake_anthropic)
    resp = client.post("/v1/responses", json={
        "model": "opus-5",
        "instructions": "Be terse.",
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]},
            {"type": "function_call", "call_id": "call_0", "name": "lookup", "arguments": "{\"q\":\"a\"}"},
            {"type": "function_call_output", "call_id": "call_0", "output": "result a"},
        ],
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}],
        "max_output_tokens": 256,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["object"] == "response" and body["model"] == "opus-5"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0]["text"] == "Hello from Opus"
    call = body["output"][1]
    assert call["type"] == "function_call" and call["name"] == "lookup"
    assert json.loads(call["arguments"]) == {"q": "x"}
    assert body["usage"]["input_tokens"] == 12 and body["usage"]["output_tokens"] == 4

    sent = seen["request"]
    assert sent["model"] == "claude-opus-5"
    assert sent["max_tokens"] == 256
    kinds = [block.get("type") for m in sent["messages"] if isinstance(m["content"], list) for block in m["content"]]
    assert "tool_use" in kinds and "tool_result" in kinds


def test_opus5_streaming_bridge_emits_responses_events(client, anthropic_token, monkeypatch):
    def chunk(delta, finish=None, usage=None):
        obj = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "model": "opus-5",
               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
        if usage:
            obj["usage"] = usage
        return f"data: {json.dumps(obj)}\n\n"

    async def fake_stream(*args, **kwargs):
        yield chunk({"role": "assistant", "content": "Hel"})
        yield chunk({"content": "lo"})
        yield chunk({"tool_calls": [{"index": 0, "id": "toolu_1", "type": "function",
                                     "function": {"name": "lookup", "arguments": ""}}]})
        yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": "{\"q\":"}}]})
        yield chunk({"tool_calls": [{"index": 0, "function": {"arguments": "\"x\"}"}}]})
        yield chunk({}, finish="tool_calls", usage={"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12})
        yield "data: [DONE]\n\n"

    monkeypatch.setattr(openai_chat, "create_openai_stream", fake_stream)
    resp = client.post("/v1/responses", json={"model": "opus-5", "input": "hi", "stream": True})
    assert resp.status_code == 200
    events = _parse_events(resp.text)
    types = [e["type"] for e in events]
    assert types == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [e["sequence_number"] for e in events] == list(range(len(events)))
    completed = events[-1]["response"]
    assert completed["status"] == "completed"
    assert completed["usage"]["input_tokens"] == 9 and completed["usage"]["output_tokens"] == 3
    assert completed["output"][0]["content"][0]["text"] == "Hello"
    assert completed["output"][1] == {
        "id": completed["output"][1]["id"], "type": "function_call", "status": "completed",
        "arguments": "{\"q\":\"x\"}", "call_id": "toolu_1", "name": "lookup",
    }


def test_streaming_bridge_upstream_400_before_output_is_400(client, anthropic_token, monkeypatch):
    async def fake_stream(*args, **kwargs):
        yield f"data: {json.dumps({'error': {'message': 'prompt is too long', 'type': 'invalid_request_error'}})}\n\n"

    monkeypatch.setattr(openai_chat, "create_openai_stream", fake_stream)
    resp = client.post("/v1/responses", json={"model": "opus-5", "input": "hi", "stream": True})
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "prompt is too long"


def test_bridge_upstream_400_non_stream_is_400(client, anthropic_token, monkeypatch):
    async def fake_anthropic(*args):
        return httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "bad tools"}})

    monkeypatch.setattr(openai_chat, "make_anthropic_request", fake_anthropic)
    resp = client.post("/v1/responses", json={"model": "opus-5", "input": "hi"})
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "bad tools"


# --- pure translation helpers --------------------------------------------------

def test_normalize_accepts_both_message_forms():
    items = normalize_responses_input([
        {"role": "assistant", "content": "prior"},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "x"}]},
        {"type": "function_call_output", "call_id": "c", "output": "o"},
    ])
    assert items[0]["content"] == [{"type": "output_text", "text": "prior"}]
    assert items[1]["content"] == [{"type": "input_text", "text": "x"}]
    assert items[2] == {"type": "function_call_output", "call_id": "c", "output": "o"}


def test_responses_to_chat_request_maps_tools_and_choice():
    chat = responses_to_chat_request({
        "input": "hi", "stream": True, "reasoning": {"effort": "high"},
        "tools": [{"type": "function", "name": "f", "description": "d", "parameters": {"type": "object"}},
                  {"type": "web_search"}],
        "tool_choice": {"type": "function", "name": "f"},
    }, "opus-5")
    assert chat["messages"] == [{"role": "user", "content": "hi"}]
    assert chat["tools"] == [{"type": "function", "function": {"name": "f", "description": "d", "parameters": {"type": "object"}}}]
    assert chat["tool_choice"] == {"type": "function", "function": {"name": "f"}}
    assert chat["reasoning_effort"] == "high"
    assert chat["stream_options"] == {"include_usage": True}
