"""Pydantic models for Anthropic API"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ThinkingParameter(BaseModel):
    """Anthropic thinking/reasoning parameter"""
    type: str = Field(default="enabled")
    budget_tokens: int = Field(default=16000)


class OutputConfig(BaseModel):
    """Anthropic output configuration (Opus 4.5 only)

    The effort parameter controls how much reasoning effort Claude puts into the response.
    Valid values: "low", "medium", "high"

    Requires beta header: effort-2025-11-24
    """
    effort: Optional[str] = None  # "low", "medium", "high"


class ContextManagement(BaseModel):
    """Anthropic context management configuration

    Allows editing the conversation context programmatically.
    Requires beta header: context-management-2025-06-27
    """
    edits: Optional[List[Dict[str, Any]]] = None


class AnthropicMessageRequest(BaseModel):
    """Anthropic Messages API request model"""
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: int
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    system: Optional[List[Dict[str, Any]]] = None
    stream: Optional[bool] = False
    thinking: Optional[ThinkingParameter] = None
    tools: Optional[List[Dict[str, Any]]] = None
    # Additional API parameters
    stop_sequences: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    service_tier: Optional[str] = None  # "auto" or "standard_only"
    tool_choice: Optional[Dict[str, Any]] = None
    # Opus 4.5 features
    output_config: Optional[OutputConfig] = None  # Effort parameter (Opus 4.5 only)
    # Context management features
    context_management: Optional[ContextManagement] = None  # Context editing
