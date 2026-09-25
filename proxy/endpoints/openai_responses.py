"""OpenAI Responses API endpoint (/v1/responses).

Routing mirrors /v1/chat/completions:

* ChatGPT models go to the ChatGPT/Codex Responses backend natively, with the
  registry id resolved to the upstream base model + reasoning effort, the
  input normalised to the list form, and only backend-supported fields kept.
* Anthropic and custom-provider models are bridged through the existing
  chat-completions pipeline and translated back into a Responses object or a
  Responses SSE stream.

Upstream 4xx errors are returned with the same status and the upstream
message; 5xx is reserved for proxy faults (502 for upstream 5xx/transport).
"""
import json
import logging
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

import settings
from chatgpt_oauth.session import ensure_session_id
from models import (
    MODEL_REGISTRY,
    get_chatgpt_default_instructions,
    is_chatgpt_model,
    is_custom_model,
    resolve_chatgpt_model,
)
from stream_debug import maybe_create_stream_tracer
from providers.tool_names import (
    ToolNameMap,
    restore_response_object,
    restore_responses_event,
    sanitize_responses_payload,
)
from proxy.endpoints import openai_chat
from proxy.endpoints.responses_translation import (
    ChatToResponsesStream,
    ResponsesInputError,
    UpstreamResponseFailed,
    chat_completion_to_response,
    fold_responses_sse,
    iter_sse_events,
    normalize_responses_input,
    responses_to_chat_request,
    stream_error_of,
    upstream_error_message,
)
from ..models import OpenAIChatCompletionRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# Fields the ChatGPT/Codex Responses backend accepts (verified live 2026-09-25:
# max_output_tokens, previous_response_id, temperature, top_p, metadata,
# truncation, user and store=true are all rejected with a 400).
_CHATGPT_PASSTHROUGH_FIELDS = ("tools", "tool_choice", "parallel_tool_calls", "include", "text")
_CHATGPT_DROPPED_FIELDS = (
    "max_output_tokens", "previous_response_id", "temperature", "top_p",
    "metadata", "truncation", "user", "service_tier",
)
_SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}


class UnknownModelError(ValueError):
    pass


def error_response(status: int, message: str, kind: Optional[str] = None) -> JSONResponse:
    if kind is None:
        kind = "invalid_request_error" if 400 <= status < 500 else "api_error"
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": kind, "code": status}})


def resolve_responses_route(model: str) -> str:
    """Return "chatgpt" or "chat" for a client model id; raise for unknown ids."""
    if is_chatgpt_model(model):
        return "chatgpt"
    if is_custom_model(model) or model in MODEL_REGISTRY or model.lower().startswith("claude-"):
        return "chat"
    raise UnknownModelError(
        f"Unknown model '{model}'. Use an id from GET /v1/models."
    )


def build_chatgpt_payload(payload: Dict[str, Any], model: str, input_items: list) -> Dict[str, Any]:
    """Build the Codex backend payload from a client Responses request."""
    upstream_model, suffix_effort = resolve_chatgpt_model(model)

    instructions = payload.get("instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        instructions = get_chatgpt_default_instructions(model) or "You are a helpful coding assistant."

    clean: Dict[str, Any] = {
        "model": upstream_model,
        "input": input_items,
        "instructions": instructions,
        "store": False,  # the backend rejects anything else
        "stream": True,  # the backend rejects stream=false; non-stream is folded
        "prompt_cache_key": ensure_session_id(instructions, input_items, payload.get("prompt_cache_key")),
    }
    for key in _CHATGPT_PASSTHROUGH_FIELDS:
        if key in payload:
            clean[key] = payload[key]

    reasoning = dict(payload["reasoning"]) if isinstance(payload.get("reasoning"), dict) else {}
    if suffix_effort and not reasoning.get("effort"):
        reasoning["effort"] = suffix_effort
        if "summary" not in reasoning and settings.CHATGPT_DEFAULT_REASONING_SUMMARY != "none":
            reasoning["summary"] = settings.CHATGPT_DEFAULT_REASONING_SUMMARY
    if reasoning:
        clean["reasoning"] = reasoning
        clean.setdefault("include", ["reasoning.encrypted_content"])
    return clean


def restore_sse_line(line: str, tool_names: ToolNameMap) -> str:
    """Map aliased tool names back in one upstream SSE `data:` line."""
    if tool_names.is_identity or not line.startswith("data:"):
        return line
    try:
        event = json.loads(line[len("data:"):].strip())
    except json.JSONDecodeError:
        return line
    return "data: " + json.dumps(restore_responses_event(event, tool_names), separators=(",", ":"))


def _dropped_fields(payload: Dict[str, Any]) -> list:
    dropped = [k for k in _CHATGPT_DROPPED_FIELDS if payload.get(k) is not None]
    if payload.get("store"):
        dropped.append("store=true")
    return dropped


def _make_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Indirection so tests can inject a MockTransport."""
    return httpx.AsyncClient(timeout=timeout)


async def run_chat_completion(chat_request: Dict[str, Any], raw_request: Request):
    """Run a chat-completions request through the existing pipeline."""
    return await openai_chat.openai_chat_completions(OpenAIChatCompletionRequest(**chat_request), raw_request)


@router.post("/v1/responses")
async def openai_responses(raw_request: Request):
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] ===== NEW OPENAI RESPONSES API REQUEST =====")

    try:
        payload = await raw_request.json()
    except Exception as e:
        logger.error(f"[{request_id}] Failed to parse request JSON: {e}")
        return error_response(400, "Invalid JSON body")
    if not isinstance(payload, dict) or not isinstance(payload.get("model"), str) or not payload["model"]:
        return error_response(400, "Request body must be an object with a 'model' string")

    model = payload["model"]
    try:
        route = resolve_responses_route(model)
        input_items = normalize_responses_input(payload.get("input"))
    except (UnknownModelError, ResponsesInputError) as e:
        logger.warning(f"[{request_id}] Rejecting /v1/responses request: {e}")
        return error_response(400, str(e))

    logger.info(f"[{request_id}] Model: {model} | stream={bool(payload.get('stream'))} | route={route}")
    if route == "chatgpt":
        return await _chatgpt_responses(request_id, payload, model, input_items)
    return await _bridged_responses(request_id, payload, model, raw_request)


# ---------------------------------------------------------------------------
# ChatGPT/Codex backend (native Responses)
# ---------------------------------------------------------------------------

async def _chatgpt_responses(request_id: str, payload: Dict[str, Any], model: str, input_items: list):
    access_token, account_id = await openai_chat.chatgpt_oauth_manager.get_auth_credentials_async()
    if not access_token or not account_id:
        logger.error(f"[{request_id}] No valid ChatGPT OAuth credentials available")
        return error_response(401, "No valid ChatGPT OAuth credentials available", "authentication_error")

    upstream_payload = build_chatgpt_payload(payload, model, input_items)
    # The backend rejects tool names outside ^[a-zA-Z0-9_-]+$ (Letta's
    # canvas.* host tools); alias them upstream, map them back downstream.
    tool_names = sanitize_responses_payload(upstream_payload)
    if not tool_names.is_identity:
        logger.info(f"[{request_id}] Aliased tool names for ChatGPT: {tool_names.aliases()}")
    dropped = _dropped_fields(payload)
    if dropped:
        logger.info(f"[{request_id}] Dropping fields unsupported by the ChatGPT backend: {dropped}")
    logger.info(
        f"[{request_id}] ChatGPT upstream model={upstream_payload['model']} "
        f"effort={(upstream_payload.get('reasoning') or {}).get('effort')}"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "session_id": upstream_payload["prompt_cache_key"],
    }

    client = _make_client(httpx.Timeout(settings.STREAM_TIMEOUT, connect=settings.CONNECT_TIMEOUT, read=settings.READ_TIMEOUT))
    try:
        upstream = await client.send(
            client.build_request("POST", settings.CHATGPT_API_ENDPOINT, json=upstream_payload, headers=headers),
            stream=True,
        )
    except httpx.HTTPError as e:
        await client.aclose()
        logger.error(f"[{request_id}] ChatGPT transport error: {e}")
        return error_response(502, f"ChatGPT upstream unreachable: {e}")

    if upstream.status_code != 200:
        body = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        message = upstream_error_message(body)
        logger.error(f"[{request_id}] ChatGPT error {upstream.status_code}: {message}")
        status = upstream.status_code if 400 <= upstream.status_code < 500 else 502
        return error_response(status, message)

    if not payload.get("stream"):
        try:
            return restore_response_object(await fold_responses_sse(upstream.aiter_bytes()), tool_names)
        except UpstreamResponseFailed as e:
            logger.error(f"[{request_id}] ChatGPT response failed: {e}")
            return error_response(e.status, str(e))
        except httpx.HTTPError as e:
            logger.error(f"[{request_id}] ChatGPT stream error: {e}")
            return error_response(502, f"ChatGPT stream error: {e}")
        finally:
            await upstream.aclose()
            await client.aclose()

    tracer = maybe_create_stream_tracer(
        enabled=settings.STREAM_TRACE_ENABLED,
        request_id=request_id,
        route="chatgpt-responses",
        base_dir=settings.STREAM_TRACE_DIR,
        max_bytes=settings.STREAM_TRACE_MAX_BYTES,
    )

    async def passthrough():
        try:
            async for line in upstream.aiter_lines():
                if tracer:
                    tracer.log_source_chunk(line + "\n")
                yield restore_sse_line(line, tool_names) + "\n"
        except Exception as e:  # upstream dropped mid-stream
            logger.error(f"[{request_id}] ChatGPT Responses stream error: {e}", exc_info=True)
            event = {"type": "error", "message": f"Stream error: {e}", "code": "upstream_stream_error"}
            yield f"event: error\ndata: {json.dumps(event)}\n\n"
        finally:
            await upstream.aclose()
            await client.aclose()
            if tracer:
                tracer.close()

    return StreamingResponse(passthrough(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ---------------------------------------------------------------------------
# Anthropic / custom providers via the chat-completions pipeline
# ---------------------------------------------------------------------------

def _http_exception_message(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return upstream_error_message(detail)
    return str(detail)


async def _bridged_responses(request_id: str, payload: Dict[str, Any], model: str, raw_request: Request):
    chat_request = responses_to_chat_request(payload, model)
    logger.info(
        f"[{request_id}] Bridging /v1/responses to chat pipeline: "
        f"{len(chat_request['messages'])} messages, {len(chat_request.get('tools') or [])} tools"
    )
    try:
        result = await run_chat_completion(chat_request, raw_request)
    except HTTPException as e:
        message = _http_exception_message(e)
        logger.error(f"[{request_id}] Bridged chat request failed {e.status_code}: {message}")
        return error_response(e.status_code, message)

    if not payload.get("stream"):
        if isinstance(result, JSONResponse):
            result = json.loads(result.body)
        return chat_completion_to_response(result, payload, model)

    events = iter_sse_events(result.body_iterator)
    first = None
    async for event_name, data in events:
        if isinstance(data, dict) or event_name == "error":
            first = (event_name, data)
            break
    if first is not None:
        error = stream_error_of(*first)
        if error:
            logger.error(f"[{request_id}] Bridged stream failed before output: {error}")
            return error_response(error["status"], error["message"], error["type"])

    translator = ChatToResponsesStream(payload, model)

    async def translate():
        for event in translator.start():
            yield event
        pending = [first] if first is not None else []
        try:
            async def all_events():
                for item in pending:
                    yield item
                async for item in events:
                    yield item

            async for event_name, data in all_events():
                error = stream_error_of(event_name, data)
                if error:
                    for event in translator.fail(error["message"], error["type"]):
                        yield event
                    return
                if isinstance(data, dict):
                    for event in translator.feed(data):
                        yield event
        except Exception as e:
            logger.error(f"[{request_id}] Bridged stream error: {e}", exc_info=True)
            for event in translator.fail(f"Stream error: {e}"):
                yield event
            return
        for event in translator.finish():
            yield event

    return StreamingResponse(translate(), media_type="text/event-stream", headers=_SSE_HEADERS)
