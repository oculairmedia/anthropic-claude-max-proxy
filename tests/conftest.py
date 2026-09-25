"""Shared fixtures: an app with the /v1/responses router and a mocked ChatGPT backend."""
import json
import os
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy.endpoints import openai_chat, openai_responses  # noqa: E402


def _sse(obj, event=None):
    head = f"event: {event}\n" if event else ""
    return f"{head}data: {json.dumps(obj)}\n\n"


CODEX_TEXT_STREAM = "".join([
    _sse({"type": "response.created", "response": {"id": "resp_1", "status": "in_progress", "output": []}}, "response.created"),
    _sse({"type": "response.output_item.added", "output_index": 0,
          "item": {"id": "msg_1", "type": "message", "status": "in_progress", "content": [], "role": "assistant"}},
         "response.output_item.added"),
    _sse({"type": "response.output_text.delta", "output_index": 0, "item_id": "msg_1", "content_index": 0, "delta": "Hi!"},
         "response.output_text.delta"),
    _sse({"type": "response.output_item.done", "output_index": 0,
          "item": {"id": "msg_1", "type": "message", "status": "completed", "role": "assistant",
                   "content": [{"type": "output_text", "annotations": [], "text": "Hi!"}]}},
         "response.output_item.done"),
    _sse({"type": "response.completed", "response": {"id": "resp_1", "object": "response", "status": "completed",
                                                     "model": "gpt-5.6-sol", "output": [],
                                                     "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}}},
         "response.completed"),
])


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(openai_responses.router)
    return TestClient(app)


@pytest.fixture
def chatgpt_upstream(monkeypatch):
    """Mock ChatGPT OAuth + backend; returns a dict capturing the upstream call."""
    captured = {"status": 200, "body": CODEX_TEXT_STREAM}

    async def creds():
        return "token", "account"

    def handler(request: httpx.Request):
        captured["payload"] = json.loads(request.content)
        captured["headers"] = dict(request.headers)
        return httpx.Response(captured["status"], content=captured["body"].encode(),
                              headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(openai_chat.chatgpt_oauth_manager, "get_auth_credentials_async", creds)
    monkeypatch.setattr(openai_responses, "_make_client",
                        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return captured


