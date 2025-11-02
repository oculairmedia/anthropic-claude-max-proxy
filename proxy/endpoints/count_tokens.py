"""
Anthropic count_tokens endpoint handler.
This endpoint is used for API key validation and token counting.
"""
import logging
import uuid
from typing import List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()


class Message(BaseModel):
    role: str
    content: str


class CountTokensRequest(BaseModel):
    model: str
    messages: List[Message]
    system: str = None
    tools: List[Dict[str, Any]] = None


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: CountTokensRequest, raw_request: Request):
    """
    Count tokens for Anthropic messages.
    This is a simplified implementation that returns reasonable estimates.
    """
    request_id = str(uuid.uuid4())[:8]
    logger.info(f"[{request_id}] Count tokens request for model: {request.model}")

    # Simple token counting estimation (roughly 4 chars per token)
    total_chars = 0

    # Count message tokens
    for message in request.messages:
        total_chars += len(message.content)

    # Count system message tokens if present
    if request.system:
        total_chars += len(request.system)

    # Count tool tokens if present
    if request.tools:
        import json
        total_chars += len(json.dumps(request.tools))

    # Rough estimate: 4 characters per token
    estimated_tokens = max(1, total_chars // 4)

    logger.debug(f"[{request_id}] Estimated {estimated_tokens} tokens from {total_chars} characters")

    # Return response in Anthropic format
    return {
        "input_tokens": estimated_tokens
    }
