"""
Storage for thinking blocks from assistant messages.

When thinking is enabled but clients don't preserve thinking blocks,
we store them server-side and re-inject them into subsequent requests.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

# In-memory storage for thinking blocks by conversation
# Key: conversation_id (derived from messages), Value: list of thinking blocks
_thinking_blocks_cache: Dict[str, List[Dict[str, Any]]] = defaultdict(list)


def extract_conversation_id(messages: List[Dict[str, Any]]) -> str:
    """Generate a conversation ID from messages for caching purposes."""
    # Use the first few messages as a conversation identifier
    # This is a simple approach - could be improved with proper session tracking
    id_parts = []
    for msg in messages[:3]:  # Use first 3 messages as ID
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            content_preview = content[:50]
        elif isinstance(content, list) and content:
            first_item = content[0]
            if isinstance(first_item, dict):
                content_preview = first_item.get("type", "")
            else:
                content_preview = str(first_item)[:50]
        else:
            content_preview = ""
        id_parts.append(f"{role}:{content_preview}")

    conversation_id = "|".join(id_parts)
    # Hash it to make it shorter
    import hashlib
    return hashlib.md5(conversation_id.encode()).hexdigest()


def store_thinking_blocks(messages: List[Dict[str, Any]], response: Dict[str, Any]) -> None:
    """Extract and store thinking blocks from an assistant response."""
    content = response.get("content", [])
    if not isinstance(content, list):
        return

    thinking_blocks = []
    for block in content:
        if isinstance(block, dict):
            block_type = block.get("type")
            if block_type in ("thinking", "redacted_thinking"):
                thinking_blocks.append(block)
                logger.debug(f"Stored {block_type} block with keys: {block.keys()}")

    if thinking_blocks:
        conv_id = extract_conversation_id(messages)
        _thinking_blocks_cache[conv_id] = thinking_blocks
        logger.info(f"Stored {len(thinking_blocks)} thinking blocks for conversation {conv_id[:8]}...")


def inject_thinking_blocks(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Inject stored thinking blocks into assistant messages that are missing them."""
    conv_id = extract_conversation_id(messages)
    stored_blocks = _thinking_blocks_cache.get(conv_id, [])

    # If no stored blocks, we can't fix the messages
    # The client needs to preserve thinking blocks themselves
    if not stored_blocks:
        logger.debug(f"No stored thinking blocks for conversation {conv_id[:8]}...")
        return messages

    updated_messages = []
    for i, message in enumerate(messages):
        if message.get("role") != "assistant":
            updated_messages.append(message)
            continue

        content = message.get("content", [])

        # Check if the first block is a thinking block
        needs_thinking_prefix = False
        if isinstance(content, list) and content:
            first_block = content[0]
            if isinstance(first_block, dict):
                first_type = first_block.get("type")
                # If first block is NOT thinking/redacted_thinking, we need to add one
                if first_type not in ("thinking", "redacted_thinking"):
                    needs_thinking_prefix = True
                    logger.debug(f"Assistant message {i} starts with {first_type}, needs thinking prefix")
        elif isinstance(content, str):
            # String content always needs thinking prefix
            needs_thinking_prefix = True
        elif not content:
            # Empty content needs thinking prefix
            needs_thinking_prefix = True

        if not needs_thinking_prefix:
            # Already starts with thinking block, keep as is
            updated_messages.append(message)
        else:
            # Need to inject stored thinking blocks at the beginning
            new_message = message.copy()

            # Convert content to list if it's a string
            if isinstance(content, str):
                content_list = [{"type": "text", "text": content}] if content else []
            elif isinstance(content, list):
                content_list = content.copy()
            else:
                content_list = []

            # Prepend the stored thinking blocks
            new_content = stored_blocks.copy()
            new_content.extend(content_list)
            new_message["content"] = new_content

            updated_messages.append(new_message)
            logger.debug(f"Injected {len(stored_blocks)} thinking blocks into assistant message {i}")

    return updated_messages


def clear_conversation_cache(conversation_id: Optional[str] = None) -> None:
    """Clear cached thinking blocks for a conversation or all conversations."""
    if conversation_id:
        if conversation_id in _thinking_blocks_cache:
            del _thinking_blocks_cache[conversation_id]
            logger.debug(f"Cleared thinking blocks for conversation {conversation_id[:8]}...")
    else:
        _thinking_blocks_cache.clear()
        logger.debug("Cleared all cached thinking blocks")
