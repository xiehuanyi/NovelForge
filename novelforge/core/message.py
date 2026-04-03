"""Message passing system for inter-agent communication.

Implements three communication patterns commonly discussed in multi-agent systems:

1. **Direct messaging**: Agent A sends to Agent B via MessageBus.send()
2. **Broadcast**: Agent A sends to all agents via MessageBus.broadcast()
3. **Blackboard**: Shared state via MessageBus.blackboard (read/write by any agent)

This design is inspired by:
- Claude Code's tool dispatch and agent spawning model
- MetaGPT's message subscription mechanism
- Classical blackboard architecture from AI textbooks
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class MessageType(Enum):
    """Types of messages that flow between agents."""
    # Pipeline messages: output of one stage, input to next
    WORLD_BIBLE = "world_bible"
    CHARACTER_PROFILES = "character_profiles"
    OUTLINE = "outline"
    CHAPTER_DRAFT = "chapter_draft"
    CHAPTER_FINAL = "chapter_final"

    # Control messages
    TASK_ASSIGN = "task_assign"
    TASK_COMPLETE = "task_complete"
    REVIEW_REQUEST = "review_request"
    REVIEW_RESULT = "review_result"
    REVISION_REQUEST = "revision_request"

    # Memory messages
    MEMORY_UPDATE = "memory_update"
    CONSISTENCY_ALERT = "consistency_alert"

    # System
    STATUS = "status"
    ERROR = "error"


@dataclass
class Message:
    """A message passed between agents.

    Fields:
        sender: ID of the sending agent
        receiver: ID of the receiving agent (None for broadcasts)
        msg_type: categorizes the message for routing
        content: the main payload (usually text)
        metadata: structured data (e.g., chapter number, scores)
        timestamp: when the message was created
    """
    sender: str
    receiver: Optional[str]
    msg_type: MessageType
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# Type alias for message handler callbacks
MessageHandler = Callable[[Message], None]


class MessageBus:
    """Central message bus for agent communication.

    Provides three communication patterns:
    1. send() — point-to-point delivery
    2. broadcast() — deliver to all subscribers
    3. blackboard — shared mutable state dictionary

    Agents subscribe to messages by registering handlers for their agent_id.
    The bus also maintains a full message history for debugging and replay.
    """

    def __init__(self):
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._global_handlers: list[MessageHandler] = []
        self.history: list[Message] = []
        self.blackboard: dict[str, Any] = {}

    def subscribe(self, agent_id: str, handler: MessageHandler) -> None:
        """Register a handler for messages addressed to agent_id."""
        self._handlers.setdefault(agent_id, []).append(handler)

    def subscribe_all(self, handler: MessageHandler) -> None:
        """Register a handler that receives all messages (for logging/TUI)."""
        self._global_handlers.append(handler)

    def send(self, message: Message) -> None:
        """Send a message to its designated receiver."""
        self.history.append(message)
        # Notify global observers
        for h in self._global_handlers:
            h(message)
        # Deliver to target
        if message.receiver and message.receiver in self._handlers:
            for h in self._handlers[message.receiver]:
                h(message)

    def broadcast(self, message: Message) -> None:
        """Broadcast a message to all registered agents."""
        self.history.append(message)
        for h in self._global_handlers:
            h(message)
        for handlers in self._handlers.values():
            for h in handlers:
                h(message)

    def query_history(
        self,
        sender: Optional[str] = None,
        msg_type: Optional[MessageType] = None,
        limit: int = 10,
    ) -> list[Message]:
        """Query message history with optional filters."""
        results = self.history
        if sender:
            results = [m for m in results if m.sender == sender]
        if msg_type:
            results = [m for m in results if m.msg_type == msg_type]
        return results[-limit:]
