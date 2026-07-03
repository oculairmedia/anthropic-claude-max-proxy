from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from chatgpt_oauth import ChatGPTOAuthManager
from settings import CHATGPT_CODEX_BASE_URL, CONNECT_TIMEOUT, READ_TIMEOUT, STREAM_TIMEOUT

logger = logging.getLogger(__name__)

API_MODEL = "gpt-image-2"
CODEX_CHAT_MODEL = "gpt-5.4"
CODEX_INSTRUCTIONS = (
    "You are an assistant that must fulfill image generation requests by "
    "using the image_generation tool when provided."
)

QUALITY_BY_MODEL = {
    "gpt-image-2-low": "low",
    "gpt-image-2-medium": "medium",
    "gpt-image-2-high": "high",
}

ALLOWED_SIZES = {"1024x1024", "1024x1536", "1536x1024"}
ALLOWED_QUALITIES = {"low", "medium", "high"}


class ChatGPTImageProvider:
    def __init__(self, oauth_manager: Optional[ChatGPTOAuthManager] = None):
        self.oauth_manager = oauth_manager or ChatGPTOAuthManager()
        self.endpoint = f"{CHATGPT_CODEX_BASE_URL}/responses"

    def _get_headers(self, access_token: str, account_id: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "chatgpt-account-id": account_id,
            "ChatGPT-Account-ID": account_id,
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
            "User-Agent": "codex_cli_rs/0.0.0 (LLMux)",
        }

    def _build_payload(self, prompt: str, model: str, size: str, quality: str, background: str, output_format: str) -> Dict[str, Any]:
        return {
            "model": CODEX_CHAT_MODEL,
            "store": False,
            "instructions": CODEX_INSTRUCTIONS,
            "input": [{
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }],
            "tools": [{
                "type": "image_generation",
                "model": model,
                "size": size,
                "quality": quality,
                "output_format": output_format,
                "background": background,
                "partial_images": 1,
            }],
            "tool_choice": {
                "type": "allowed_tools",
                "mode": "required",
                "tools": [{"type": "image_generation"}],
            },
            "stream": True,
        }

    async def generate_image_b64(self, request_data: Dict[str, Any], request_id: str) -> str:
        access_token, account_id = await self.oauth_manager.get_auth_credentials_async()
        if not access_token or not account_id:
            raise ValueError("No valid ChatGPT OAuth credentials available")

        prompt = str(request_data.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Prompt is required and must be a non-empty string")

        model, quality = self._resolve_model_and_quality(request_data)
        size = self._resolve_size(request_data.get("size"))
        background = self._resolve_background(request_data.get("background"))
        output_format = self._resolve_output_format(request_data.get("output_format"))
        payload = self._build_payload(prompt, model, size, quality, background, output_format)
        headers = self._get_headers(access_token, account_id)

        logger.debug(f"[{request_id}] Making ChatGPT image request to {self.endpoint}")
        logger.debug(f"[{request_id}] Image request payload: {json.dumps(payload, indent=2)}")

        image_b64: Optional[str] = None
        timeout = httpx.Timeout(STREAM_TIMEOUT, connect=CONNECT_TIMEOUT, read=READ_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", self.endpoint, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    error_text = (await response.aread()).decode(errors="replace")
                    logger.error(f"[{request_id}] ChatGPT image error {response.status_code}: {error_text}")
                    raise RuntimeError(f"ChatGPT image API error {response.status_code}: {error_text[:500]}")

                async for event in self._iter_sse_json(response):
                    found = self._extract_image_b64(event)
                    if found:
                        image_b64 = found

        if not image_b64:
            raise RuntimeError("Codex response contained no image_generation_call result")
        return image_b64

    def _resolve_model_and_quality(self, request_data: Dict[str, Any]) -> tuple[str, str]:
        requested_model = str(request_data.get("model") or API_MODEL)
        requested_quality = request_data.get("quality")

        if requested_model in QUALITY_BY_MODEL:
            return API_MODEL, QUALITY_BY_MODEL[requested_model]

        quality = str(requested_quality or "medium")
        if quality == "auto":
            quality = "medium"
        if quality not in ALLOWED_QUALITIES:
            quality = "medium"
        return API_MODEL, quality

    def _resolve_size(self, value: Any) -> str:
        size = str(value or "1024x1024")
        if size == "auto":
            return "1024x1024"
        if size not in ALLOWED_SIZES:
            return "1024x1024"
        return size

    def _resolve_background(self, value: Any) -> str:
        background = str(value or "opaque")
        if background not in {"auto", "opaque", "transparent"}:
            return "opaque"
        return background

    def _resolve_output_format(self, value: Any) -> str:
        output_format = str(value or "png")
        if output_format not in {"png", "jpeg", "webp"}:
            return "png"
        return output_format

    async def _iter_sse_json(self, response: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
        event_name: Optional[str] = None
        data_lines: list[str] = []

        async for line in response.aiter_lines():
            if line == "":
                payload = self._flush_sse_event(event_name, data_lines)
                event_name = None
                data_lines = []
                if payload is not None:
                    yield payload
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].lstrip())

        payload = self._flush_sse_event(event_name, data_lines)
        if payload is not None:
            yield payload

    def _flush_sse_event(self, event_name: Optional[str], data_lines: list[str]) -> Optional[Dict[str, Any]]:
        if not data_lines:
            return None
        raw = "\n".join(data_lines).strip()
        if not raw or raw == "[DONE]":
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict) and event_name and "type" not in payload:
            payload["type"] = event_name
        return payload if isinstance(payload, dict) else None

    def _extract_image_b64(self, value: Any) -> Optional[str]:
        found: Optional[str] = None
        if isinstance(value, dict):
            if value.get("type") == "image_generation_call":
                result = value.get("result")
                if isinstance(result, str) and result:
                    found = result
            partial = value.get("partial_image_b64")
            if isinstance(partial, str) and partial:
                found = partial
            for child in value.values():
                nested = self._extract_image_b64(child)
                if nested:
                    found = nested
        elif isinstance(value, list):
            for child in value:
                nested = self._extract_image_b64(child)
                if nested:
                    found = nested
        return found
