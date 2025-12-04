"""Anthropic API integration package"""

from .models import ThinkingParameter, AnthropicMessageRequest
from .request_sanitizer import sanitize_anthropic_request
from .system_message import inject_claude_code_system_message
from .prompt_caching import add_prompt_caching, count_existing_cache_controls
from .api_client import make_anthropic_request, stream_anthropic_response
from .thinking_keywords import (
    detect_thinking_keyword,
    strip_thinking_keywords,
    get_thinking_config,
    process_thinking_keywords,
)

__all__ = [
    "ThinkingParameter",
    "AnthropicMessageRequest",
    "sanitize_anthropic_request",
    "inject_claude_code_system_message",
    "add_prompt_caching",
    "count_existing_cache_controls",
    "make_anthropic_request",
    "stream_anthropic_response",
    "detect_thinking_keyword",
    "strip_thinking_keywords",
    "get_thinking_config",
    "process_thinking_keywords",
]
