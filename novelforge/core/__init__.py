"""Core abstractions: Agent, Message, LLM client."""

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import Message, MessageBus, MessageType
from novelforge.core.llm import LLMClient
from novelforge.core.config import Config

__all__ = [
    "Agent", "AgentRole",
    "Message", "MessageBus", "MessageType",
    "LLMClient",
    "Config",
]
