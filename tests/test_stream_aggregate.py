import asyncio
import json

import pytest

from proxy.endpoints.openai_stream_aggregate import UpstreamStreamError, aggregate_openai_sse


def _sse(obj):
    return f"data: {json.dumps(obj)}\n\n"


async def _chunks(items):
    for item in items:
        yield item


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_content_chunks_fold_into_one_completion():
    chunks = [
        _sse({"id": "chatcmpl-1", "model": "gpt-6-sol", "created": 5, "choices": [{"index": 0, "delta": {"role": "assistant", "content": "ok"}, "finish_reason": None}]}),
        _sse({"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {"content": "."}, "finish_reason": None}]}),
        _sse({"id": "chatcmpl-1", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}),
        "data: [DONE]\n\n",
    ]
    result = _run(aggregate_openai_sse(_chunks(chunks), fallback_model="x"))
    assert result["object"] == "chat.completion"
    assert result["id"] == "chatcmpl-1"
    assert result["model"] == "gpt-6-sol"
    assert result["choices"][0]["message"] == {"role": "assistant", "content": "ok."}
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"]["total_tokens"] == 5


def test_tool_call_arguments_are_concatenated_by_index():
    chunks = [
        _sse({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":"}}]}, "finish_reason": None}]}),
        _sse({"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"sol\"}"}}]}, "finish_reason": None}]}),
        _sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}),
    ]
    result = _run(aggregate_openai_sse(_chunks(chunks), fallback_model="gpt-6-sol"))
    message = result["choices"][0]["message"]
    assert message["content"] is None
    assert message["tool_calls"] == [{"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":\"sol\"}"}}]
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    assert result["model"] == "gpt-6-sol"


def test_error_event_raises():
    chunks = [_sse({"error": {"message": "ChatGPT API error: 400", "upstream_body": "x"}})]
    with pytest.raises(UpstreamStreamError, match="ChatGPT API error: 400"):
        _run(aggregate_openai_sse(_chunks(chunks), fallback_model="gpt-6-sol"))
