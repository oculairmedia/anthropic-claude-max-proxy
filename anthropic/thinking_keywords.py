"""Thinking keyword detection for Claude models.

Detects keywords like 'think', 'think hard', 'think harder', 'ultrathink' in user messages
and configures extended thinking with appropriate budgets.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Keyword to thinking budget mapping (tokens)
# Based on Anthropic's Claude Code keywords
# Order matters for regex: longer phrases must come first
THINKING_KEYWORD_MAP: Dict[str, int] = {
    "ultrathink": 32000,
    "think harder": 24000,
    "think hard": 16000,
    "think": 10000,
}

# Regex pattern to match keywords (case-insensitive, word boundaries)
# Order: longer phrases first to avoid partial matches
KEYWORD_PATTERN = re.compile(
    r'\b(ultrathink|think\s+harder|think\s+hard|think)\b',
    re.IGNORECASE
)


def _normalize_keyword(keyword: str) -> str:
    """Normalize keyword by collapsing whitespace."""
    return re.sub(r'\s+', ' ', keyword.lower().strip())


def detect_thinking_keyword(messages: List[Dict[str, Any]]) -> Optional[str]:
    """Scan messages for thinking keywords and return the highest-level one found.

    Args:
        messages: List of message dicts with 'role' and 'content' fields

    Returns:
        The highest-level keyword found (e.g., 'ultrathink'), or None if no keywords found
    """
    found_keywords: List[str] = []

    for message in messages:
        if message.get("role") != "user":
            continue

        content = message.get("content")
        if not content:
            continue

        # Handle string content
        if isinstance(content, str):
            matches = KEYWORD_PATTERN.findall(content)
            found_keywords.extend([_normalize_keyword(m) for m in matches])

        # Handle array content (OpenAI format with text blocks)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    matches = KEYWORD_PATTERN.findall(text)
                    found_keywords.extend([_normalize_keyword(m) for m in matches])

    if not found_keywords:
        return None

    # Return highest-level keyword (highest budget wins)
    highest_keyword = None
    highest_budget = 0

    for keyword in found_keywords:
        budget = THINKING_KEYWORD_MAP.get(keyword, 0)
        if budget > highest_budget:
            highest_budget = budget
            highest_keyword = keyword

    if highest_keyword:
        logger.debug(f"Detected thinking keyword: {highest_keyword} (budget: {highest_budget})")

    return highest_keyword


def strip_thinking_keywords(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove thinking keywords from message content.

    Args:
        messages: List of message dicts with 'role' and 'content' fields

    Returns:
        New list of messages with keywords stripped from user messages
    """
    result: List[Dict[str, Any]] = []

    for message in messages:
        if message.get("role") != "user":
            result.append(message)
            continue

        content = message.get("content")
        if not content:
            result.append(message)
            continue

        new_message = message.copy()

        # Handle string content
        if isinstance(content, str):
            new_content = KEYWORD_PATTERN.sub('', content)
            # Clean up extra whitespace
            new_content = re.sub(r'\s+', ' ', new_content).strip()
            new_message["content"] = new_content

        # Handle array content (OpenAI format with text blocks)
        elif isinstance(content, list):
            new_content_list: List[Dict[str, Any]] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    new_text = KEYWORD_PATTERN.sub('', text)
                    new_text = re.sub(r'\s+', ' ', new_text).strip()
                    new_item = item.copy()
                    new_item["text"] = new_text
                    new_content_list.append(new_item)
                else:
                    new_content_list.append(item)
            new_message["content"] = new_content_list

        result.append(new_message)

    return result


def get_thinking_config(keyword: str) -> Dict[str, Any]:
    """Get thinking configuration for a keyword.

    Args:
        keyword: The thinking keyword (e.g., 'ultrathink')

    Returns:
        Thinking configuration dict for Anthropic API
    """
    budget = THINKING_KEYWORD_MAP.get(keyword.lower(), 10000)

    return {
        "type": "enabled",
        "budget_tokens": budget
    }


def process_thinking_keywords(messages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Detect and process thinking keywords in messages.

    Convenience function that combines detection, stripping, and config generation.

    Args:
        messages: List of message dicts

    Returns:
        Tuple of (processed_messages, thinking_config or None)
    """
    keyword = detect_thinking_keyword(messages)

    if not keyword:
        return messages, None

    stripped_messages = strip_thinking_keywords(messages)
    thinking_config = get_thinking_config(keyword)

    logger.info(f"Processed thinking keyword '{keyword}' with budget {thinking_config['budget_tokens']}")

    return stripped_messages, thinking_config
