"""Regression tests for letta-mobile-fosvg: /v1/responses tool turns must
reach Anthropic as [text..., tool_use...], never [tool_use, text].

LiteLLM's Anthropic /v1/messages -> Responses adapter emits an assistant
turn ``[text, tool_use]`` as ``function_call`` items FIRST and the assistant
``message`` item AFTER them. Rebuilt naively, that becomes an Anthropic
assistant message ``[tool_use, text]``; when it is the last assistant turn,
Opus/Sonnet 5.5 reject the request with "This model does not support
assistant message prefill. The conversation must end with a user message."
(verified live 2026-10-29 against api.anthropic.com).

The input below is the real failing shape from a letta-code conversation
(two consecutive text+tool_use turns, then tool results), content anonymised.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from openai_compat.request_converter import convert_openai_request_to_anthropic  # noqa: E402
from proxy.endpoints.responses_translation import responses_to_chat_request  # noqa: E402


def _user(*parts):
    return {"type": "message", "role": "user", "content": list(parts)}


def _assistant_text(text):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def _call(call_id, name="Bash"):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": '{"command": "ls"}'}


def _output(call_id, text="<tool output>"):
    return {"type": "function_call_output", "call_id": call_id, "output": text}


def _to_anthropic(input_items):
    chat = responses_to_chat_request(
        {"input": input_items, "instructions": "<system>", "reasoning": {"effort": "high"}, "stream": True,
         "tools": [{"type": "function", "name": "Bash", "parameters": {"type": "object", "properties": {}}}]},
        "claude-opus-5-5",
    )
    return convert_openai_request_to_anthropic(chat)["messages"]


def _shape(messages):
    return [(m["role"], [b["type"] for b in m["content"]]) for m in messages]


def _assert_tool_use_closes_every_assistant_turn(messages):
    for m in messages:
        if m["role"] != "assistant":
            continue
        types = [b["type"] for b in m["content"]]
        if "tool_use" in types:
            first_tool = types.index("tool_use")
            assert all(t == "tool_use" for t in types[first_tool:]), types


# Real failing shape (letta-code conv, 2026-10-29 03:22Z), as LiteLLM sends it.
LETTA_TWO_TEXT_TOOL_TURNS = [
    _user({"type": "input_text", "text": "<user prompt>"},
          {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}),
    _call("toolu_A"),
    _assistant_text("<narration before tool A>"),
    _output("toolu_A"),
    _call("toolu_B"),
    _assistant_text("<narration before tool B>"),
    _output("toolu_B"),
]


def test_letta_two_text_tool_turns_keep_text_before_tool_use():
    messages = _to_anthropic(LETTA_TWO_TEXT_TOOL_TURNS)
    assert _shape(messages) == [
        ("user", ["text", "image"]),
        ("assistant", ["text", "tool_use"]),
        ("user", ["tool_result"]),
        ("assistant", ["text", "tool_use"]),
        ("user", ["tool_result"]),
    ]
    # Nothing dropped or invented: every text and tool id survives verbatim.
    assert messages[1]["content"][0]["text"] == "<narration before tool A>"
    assert messages[3]["content"][0]["text"] == "<narration before tool B>"
    assert [b["id"] for b in messages[3]["content"] if b["type"] == "tool_use"] == ["toolu_B"]
    assert messages[4]["content"][0]["tool_use_id"] == "toolu_B"
    _assert_tool_use_closes_every_assistant_turn(messages)


def test_parallel_tool_calls_with_narration():
    # Real shape from a second failing conv: text + 3 parallel tool calls.
    messages = _to_anthropic([
        _user({"type": "input_text", "text": "<prompt>"}),
        _call("toolu_1"), _call("toolu_2"), _call("toolu_3"),
        _assistant_text("<narration>"),
        _output("toolu_1"), _output("toolu_2"), _output("toolu_3"),
    ])
    assert _shape(messages) == [
        ("user", ["text"]),
        ("assistant", ["text", "tool_use", "tool_use", "tool_use"]),
        ("user", ["tool_result", "tool_result", "tool_result"]),
    ]


def test_assistant_text_after_tool_outputs_starts_a_new_turn():
    # A final answer after tool results is its own assistant turn; it must not
    # be folded back into the earlier tool-call turn.
    messages = _to_anthropic([
        _user({"type": "input_text", "text": "<prompt>"}),
        _call("toolu_A"),
        _output("toolu_A"),
        _assistant_text("<answer>"),
        _user({"type": "input_text", "text": "<follow-up>"}),
    ])
    assert _shape(messages) == [
        ("user", ["text"]),
        ("assistant", ["tool_use"]),
        ("user", ["tool_result"]),
        ("assistant", ["text"]),
        ("user", ["text"]),
    ]


def test_text_already_on_tool_turn_is_kept_in_order():
    # [message, function_call, message] for one turn: both texts survive, in
    # input order, ahead of the tool_use.
    messages = _to_anthropic([
        _user({"type": "input_text", "text": "<prompt>"}),
        _assistant_text("<first>"),
        _call("toolu_A"),
        _assistant_text("<second>"),
        _output("toolu_A"),
    ])
    assert _shape(messages)[1] == ("assistant", ["text", "text", "tool_use"])
    assert [b["text"] for b in messages[1]["content"][:2]] == ["<first>", "<second>"]


def test_upstream_400_logs_content_free_shape_of_last_three_messages(caplog):
    from anthropic.api_client import log_upstream_400_shape

    request = {"messages": [
        {"role": "user", "content": "<secret prompt>"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_A", "name": "Bash", "input": {}},
                                          {"type": "text", "text": "<secret narration>"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_A", "content": "<secret output>"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "<secret answer>"}]},
    ]}
    with caplog.at_level("WARNING", logger="anthropic.api_client"):
        log_upstream_400_shape("req12345", 200, request)
        assert not caplog.records
        log_upstream_400_shape("req12345", 400, request)
    [record] = caplog.records
    assert record.levelname == "WARNING"
    msg = record.getMessage()
    assert "[req12345]" in msg and "4 messages" in msg
    assert '{"role": "assistant", "blocks": ["tool_use", "text"]}' in msg
    assert '{"role": "assistant", "blocks": ["text"]}' in msg
    assert "secret" not in msg and "toolu_A" not in msg
