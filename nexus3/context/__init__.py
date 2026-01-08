"""Context management for NEXUS3.

This module provides utilities for loading system prompts with a fallback chain,
allowing customization at project and user levels while providing sensible defaults.
It also provides token counting functionality with pluggable backends and
context management for conversation state and token budgets.
"""

from nexus3.context.manager import ContextConfig, ContextManager
from nexus3.context.prompt_loader import LoadedPrompt, PromptLoader
from nexus3.context.token_counter import (
    SimpleTokenCounter,
    TiktokenCounter,
    TokenCounter,
    get_token_counter,
)

__all__ = [
    "LoadedPrompt",
    "PromptLoader",
    "TokenCounter",
    "SimpleTokenCounter",
    "TiktokenCounter",
    "get_token_counter",
    "ContextManager",
    "ContextConfig",
]
