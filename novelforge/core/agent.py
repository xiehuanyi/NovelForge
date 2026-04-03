"""Base Agent abstraction.

Every agent in NovelForge inherits from Agent, which provides:
- Identity (role, name, color for TUI)
- Access to LLM client and message bus
- Standard call() interface with system prompt injection
- Built-in self-reflection loop (agent reviews its own output)

Design inspiration:
- ReAct pattern: reason → act → observe → refine
- Claude Code's agent model: each agent has a system prompt + tools
- MetaGPT's role-based agent with structured output
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

from novelforge.core.config import Config
from novelforge.core.llm import LLMClient, LLMResponse
from novelforge.core.message import Message, MessageBus, MessageType

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """All agent roles in the system."""
    ORCHESTRATOR = "orchestrator"
    WORLDBUILDER = "worldbuilder"
    CHARACTER = "character"
    OUTLINER = "outliner"
    WRITER = "writer"
    EDITOR = "editor"


# Display metadata for each role
ROLE_META = {
    AgentRole.ORCHESTRATOR: {"name": "协调者", "color": "bright_yellow", "icon": "🎯"},
    AgentRole.WORLDBUILDER: {"name": "世界构建师", "color": "bright_green", "icon": "🌍"},
    AgentRole.CHARACTER:    {"name": "角色设计师", "color": "bright_cyan", "icon": "👤"},
    AgentRole.OUTLINER:     {"name": "大纲编剧", "color": "bright_blue", "icon": "📋"},
    AgentRole.WRITER:       {"name": "写手", "color": "bright_red", "icon": "✍️"},
    AgentRole.EDITOR:       {"name": "编辑", "color": "bright_magenta", "icon": "📝"},
}


class Agent(ABC):
    """Base class for all agents.

    Subclasses implement:
    - system_prompt: the agent's core instructions
    - execute(**kwargs): the agent's main logic
    """

    role: AgentRole  # Must be set by subclass

    def __init__(self, llm: LLMClient, bus: MessageBus, config: Config):
        self.llm = llm
        self.bus = bus
        self.config = config
        meta = ROLE_META.get(self.role, {})
        self.name = meta.get("name", self.role.value)
        self.color = meta.get("color", "white")
        self.icon = meta.get("icon", "")

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """The agent's system prompt defining its role and constraints."""
        ...

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """Run the agent's main task. Returns the output text."""
        ...

    def call_llm(
        self,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """Call the LLM with this agent's system prompt.

        This is the standard way for agents to interact with the LLM.
        The system prompt is automatically prepended.
        """
        self._emit_status(f"正在思考...")
        resp = self.llm.chat(
            system=self.system_prompt,
            user=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._emit_status(f"完成 (tokens: {resp.input_tokens}+{resp.output_tokens})")
        return resp

    def self_reflect(self, draft: str, criteria: str) -> str:
        """Self-reflection loop: agent reviews and improves its own output.

        This implements the Reflexion pattern (Shinn et al., 2023):
        1. Generate initial output
        2. Critique against criteria
        3. Revise based on critique

        Returns the improved output.
        """
        self._emit_status("自我审查中...")
        review_prompt = (
            f"请审查以下内容，根据标准给出具体改进建议：\n\n"
            f"【审查标准】\n{criteria}\n\n"
            f"【待审查内容】\n{draft}\n\n"
            f"请指出具体问题并给出改进建议。如果质量已经足够好，回复'通过'。"
        )
        review = self.call_llm(review_prompt, temperature=0.3)

        if "通过" in review.content and len(review.content) < 100:
            return draft

        self._emit_status("根据审查意见修订中...")
        revise_prompt = (
            f"根据以下审查意见，修订并输出完整的改进版本：\n\n"
            f"【审查意见】\n{review.content}\n\n"
            f"【原始内容】\n{draft}\n\n"
            f"请输出修订后的完整内容。"
        )
        revised = self.call_llm(revise_prompt, temperature=0.7)
        return revised.content

    def emit(self, msg_type: MessageType, content: str, **metadata) -> None:
        """Send a message on the bus."""
        msg = Message(
            sender=self.role.value,
            receiver=None,
            msg_type=msg_type,
            content=content,
            metadata=metadata,
        )
        self.bus.send(msg)

    def _emit_status(self, text: str) -> None:
        """Emit a status message for the TUI to display."""
        self.emit(MessageType.STATUS, f"[{self.name}] {text}")
