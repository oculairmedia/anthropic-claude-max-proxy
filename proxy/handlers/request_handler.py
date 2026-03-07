"""
Request preparation and conversion logic.
"""
import logging
from typing import Dict, Any

from openai_compat import convert_openai_request_to_anthropic
from anthropic import (
    sanitize_anthropic_request,
    inject_claude_code_system_message,
    add_prompt_caching,
)
from anthropic.thinking_keywords import process_thinking_keywords
from proxy.thinking_storage import inject_thinking_blocks
import settings

logger = logging.getLogger(__name__)


def prepare_anthropic_request(
    openai_request: Dict[str, Any],
    request_id: str,
    is_native_anthropic: bool = False
) -> Dict[str, Any]:
    """
    Prepare an Anthropic API request from OpenAI or native format.

    Args:
        openai_request: The request data (OpenAI or Anthropic format)
        request_id: Request ID for logging
        is_native_anthropic: If True, skip OpenAI conversion

    Returns:
        Prepared Anthropic request dict
    """
    # Convert from OpenAI format if needed
    if not is_native_anthropic:
        anthropic_request = convert_openai_request_to_anthropic(openai_request)
    else:
        anthropic_request = openai_request.copy()

    # Handle response_format (JSON mode) - inject instruction into system prompt
    response_format = openai_request.get("response_format")
    if response_format and response_format.get("type") == "json_object":
        logger.info(f"[{request_id}] JSON mode enabled via response_format")
        system_blocks = anthropic_request.get("system", [])
        if not isinstance(system_blocks, list):
            system_blocks = [{"type": "text", "text": system_blocks}] if system_blocks else []
        json_instruction = {
            "type": "text",
            "text": "IMPORTANT: You must respond with valid JSON only. No markdown code fences, no explanations, just pure JSON."
        }
        system_blocks.append(json_instruction)
        anthropic_request["system"] = system_blocks

    # Handle seed parameter - set temperature to 0 for best-effort determinism
    seed = openai_request.get("seed")
    if seed is not None:
        logger.debug(f"[{request_id}] seed={seed} (note: Anthropic doesn't guarantee determinism)")
        # Only set temperature to 0 if not already specified
        if anthropic_request.get("temperature") is None:
            anthropic_request["temperature"] = 0
            logger.debug(f"[{request_id}] Set temperature=0 for deterministic behavior")

    # Process thinking keywords in messages (detect, strip, and get config)
    messages = anthropic_request.get("messages", [])
    processed_messages, thinking_config = process_thinking_keywords(messages)

    # Check if this is a tool use continuation (assistant message with tool_use)
    has_tool_use_in_assistant = False
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        has_tool_use_in_assistant = True
                        break

    if thinking_config:
        anthropic_request["messages"] = processed_messages
        # Only set thinking if not already configured AND not in tool use continuation
        if not anthropic_request.get("thinking") and not has_tool_use_in_assistant:
            anthropic_request["thinking"] = thinking_config
            logger.info(f"[{request_id}] Injected thinking config from keyword: {thinking_config}")
        elif has_tool_use_in_assistant:
            logger.info(f"[{request_id}] Skipping thinking injection due to tool use continuation")
        else:
            # Update budget if keyword specifies higher budget
            existing_budget = anthropic_request["thinking"].get("budget_tokens", 0)
            keyword_budget = thinking_config.get("budget_tokens", 0)
            if keyword_budget > existing_budget:
                anthropic_request["thinking"]["budget_tokens"] = keyword_budget
                logger.info(f"[{request_id}] Updated thinking budget from {existing_budget} to {keyword_budget}")

    # Ensure max_tokens is sufficient if thinking is enabled
    thinking = anthropic_request.get("thinking")
    if thinking and thinking.get("type") == "enabled":
        thinking_budget = thinking.get("budget_tokens", 16000)
        min_response_tokens = 1024
        required_total = thinking_budget + min_response_tokens
        if anthropic_request["max_tokens"] < required_total:
            anthropic_request["max_tokens"] = required_total
            logger.debug(
                f"[{request_id}] Increased max_tokens to {required_total} "
                f"(thinking: {thinking_budget} + response: {min_response_tokens})"
            )

        # Inject stored thinking blocks from previous responses
        anthropic_request["messages"] = inject_thinking_blocks(anthropic_request["messages"])
        logger.debug(f"[{request_id}] Injected stored thinking blocks if available")

    # Sanitize request for Anthropic API constraints
    anthropic_request = sanitize_anthropic_request(anthropic_request)

    # Inject Claude Code system message to bypass authentication detection
    anthropic_request = inject_claude_code_system_message(anthropic_request)

    # Add cache_control to message content blocks for optimal caching
    anthropic_request = add_prompt_caching(anthropic_request, ttl=settings.CACHE_TTL)

    return anthropic_request
