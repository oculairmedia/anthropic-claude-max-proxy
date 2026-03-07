"""Request sanitization and validation for Anthropic API"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def sanitize_anthropic_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize and validate request for Anthropic API

    Args:
        request_data: Raw request data dictionary

    Returns:
        Sanitized request data dictionary
    """
    sanitized = request_data.copy()

    # Universal parameter validation - clean invalid values regardless of thinking mode
    if 'top_p' in sanitized:
        top_p_val = sanitized['top_p']
        if top_p_val is None or top_p_val == "" or not isinstance(top_p_val, (int, float)):
            logger.debug(f"Removing invalid top_p value: {top_p_val} (type: {type(top_p_val)})")
            del sanitized['top_p']
        elif not (0.0 <= top_p_val <= 1.0):
            logger.debug(f"Removing out-of-range top_p value: {top_p_val}")
            del sanitized['top_p']

    if 'temperature' in sanitized:
        temp_val = sanitized['temperature']
        if temp_val is None or temp_val == "" or not isinstance(temp_val, (int, float)):
            logger.debug(f"Removing invalid temperature value: {temp_val} (type: {type(temp_val)})")
            del sanitized['temperature']

    if 'top_k' in sanitized:
        top_k_val = sanitized['top_k']
        if top_k_val is None or top_k_val == "" or not isinstance(top_k_val, int):
            logger.debug(f"Removing invalid top_k value: {top_k_val} (type: {type(top_k_val)})")
            del sanitized['top_k']
        elif top_k_val <= 0:
            logger.debug(f"Removing invalid top_k value (must be positive): {top_k_val}")
            del sanitized['top_k']

    # Handle tools parameter - remove if null or empty list
    if 'tools' in sanitized:
        tools_val = sanitized.get('tools')
        if tools_val is None:
            logger.debug("Removing null tools parameter (Anthropic API doesn't accept null values)")
            del sanitized['tools']
        elif isinstance(tools_val, list) and len(tools_val) == 0:
            logger.debug("Removing empty tools list (Anthropic API doesn't accept empty tools list)")
            del sanitized['tools']
        elif not isinstance(tools_val, list):
            logger.debug(f"Removing invalid tools parameter (must be a list): {type(tools_val)}")
            del sanitized['tools']

    # Handle thinking parameter - remove if null/None as Anthropic API doesn't accept null values
    thinking = sanitized.get('thinking')
    if thinking is None:
        logger.debug("Removing null thinking parameter (Anthropic API doesn't accept null values)")
        sanitized.pop('thinking', None)
    elif thinking and thinking.get('type') == 'enabled':
        logger.debug("Thinking enabled - applying Anthropic API constraints")

        # Apply Anthropic thinking constraints
        if 'temperature' in sanitized and sanitized['temperature'] is not None and sanitized['temperature'] != 1.0:
            logger.debug(f"Adjusting temperature from {sanitized['temperature']} to 1.0 (thinking enabled)")
            sanitized['temperature'] = 1.0

        if 'top_p' in sanitized and sanitized['top_p'] is not None and not (0.95 <= sanitized['top_p'] <= 1.0):
            adjusted_top_p = max(0.95, min(1.0, sanitized['top_p']))
            logger.debug(f"Adjusting top_p from {sanitized['top_p']} to {adjusted_top_p} (thinking constraints)")
            sanitized['top_p'] = adjusted_top_p

        # Remove top_k as it's not allowed with thinking
        if 'top_k' in sanitized:
            logger.debug("Removing top_k parameter (not allowed with thinking)")
            del sanitized['top_k']

    # Handle stop_sequences - remove if null or empty
    if 'stop_sequences' in sanitized:
        stop_val = sanitized.get('stop_sequences')
        if stop_val is None:
            logger.debug("Removing null stop_sequences parameter")
            del sanitized['stop_sequences']
        elif isinstance(stop_val, list) and len(stop_val) == 0:
            logger.debug("Removing empty stop_sequences list")
            del sanitized['stop_sequences']
        elif not isinstance(stop_val, list):
            logger.debug(f"Removing invalid stop_sequences (must be list): {type(stop_val)}")
            del sanitized['stop_sequences']

    # Handle metadata - remove if null
    if 'metadata' in sanitized:
        meta_val = sanitized.get('metadata')
        if meta_val is None:
            logger.debug("Removing null metadata parameter")
            del sanitized['metadata']
        elif not isinstance(meta_val, dict):
            logger.debug(f"Removing invalid metadata (must be dict): {type(meta_val)}")
            del sanitized['metadata']

    # Handle service_tier - validate value
    if 'service_tier' in sanitized:
        tier_val = sanitized.get('service_tier')
        if tier_val is None:
            logger.debug("Removing null service_tier parameter")
            del sanitized['service_tier']
        elif tier_val not in ('auto', 'standard_only'):
            logger.debug(f"Removing invalid service_tier value: {tier_val}")
            del sanitized['service_tier']

    # Handle tool_choice - remove if null
    if 'tool_choice' in sanitized:
        tc_val = sanitized.get('tool_choice')
        if tc_val is None:
            logger.debug("Removing null tool_choice parameter")
            del sanitized['tool_choice']
        elif not isinstance(tc_val, dict):
            logger.debug(f"Removing invalid tool_choice (must be dict): {type(tc_val)}")
            del sanitized['tool_choice']

    # Handle output_config - validate effort values (Opus 4.5 only)
    if 'output_config' in sanitized:
        oc_val = sanitized.get('output_config')
        if oc_val is None:
            logger.debug("Removing null output_config parameter")
            del sanitized['output_config']
        elif not isinstance(oc_val, dict):
            logger.debug(f"Removing invalid output_config (must be dict): {type(oc_val)}")
            del sanitized['output_config']
        elif 'effort' in oc_val and oc_val['effort'] not in ('low', 'medium', 'high'):
            logger.debug(f"Removing invalid output_config.effort value: {oc_val['effort']}")
            del sanitized['output_config']

    # Handle context_management - validate structure
    if 'context_management' in sanitized:
        cm_val = sanitized.get('context_management')
        if cm_val is None:
            logger.debug("Removing null context_management parameter")
            del sanitized['context_management']
        elif not isinstance(cm_val, dict):
            logger.debug(f"Removing invalid context_management (must be dict): {type(cm_val)}")
            del sanitized['context_management']

    return sanitized
