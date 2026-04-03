"""Memory manager that coordinates the three memory layers.

Handles:
- Memory creation and categorization
- Automatic compression (summarizing old working memory into episodic)
- Retrieval across layers with relevance-based ranking
- Context assembly for LLM prompts

Inspired by:
- Generative Agents: importance scoring + retrieval by recency/relevance
- MemGPT: tiered memory with automatic migration between tiers
- Claude Code: file-based memory with structured index
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from novelforge.core.llm import LLMClient
from novelforge.memory.base import MemoryEntry, MemoryStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """Manages three memory layers: working, episodic, semantic.

    Working Memory: volatile, holds current chapter context.
      → After each chapter, compressed into episodic memory.

    Episodic Memory: chapter-level event records.
      → Periodically summarized into semantic memory.

    Semantic Memory: persistent facts (character states, world rules).
      → Updated when significant state changes are detected.
    """

    def __init__(self, project_dir: Path, llm: LLMClient):
        self.llm = llm
        mem_dir = project_dir / "memory"
        self.working = MemoryStore(mem_dir / "working")
        self.episodic = MemoryStore(mem_dir / "episodic")
        self.semantic = MemoryStore(mem_dir / "semantic")

    def add_working(self, key: str, content: str, chapter: int, importance: int = 5,
                    tags: Optional[list[str]] = None) -> None:
        """Add to working memory (current context)."""
        self.working.add(MemoryEntry(
            key=key, category="working", content=content,
            tags=tags or [], importance=importance, chapter=chapter,
        ))

    def add_episodic(self, key: str, content: str, chapter: int, importance: int = 5,
                     tags: Optional[list[str]] = None) -> None:
        """Add to episodic memory (event records)."""
        self.episodic.add(MemoryEntry(
            key=key, category="episodic", content=content,
            tags=tags or [], importance=importance, chapter=chapter,
        ))

    def add_semantic(self, key: str, content: str, importance: int = 7,
                     tags: Optional[list[str]] = None) -> None:
        """Add to semantic memory (facts and states)."""
        self.semantic.add(MemoryEntry(
            key=key, category="semantic", content=content,
            tags=tags or [], importance=importance,
        ))

    def compress_chapter(self, chapter_num: int, chapter_text: str) -> None:
        """Compress a completed chapter into episodic + semantic memory.

        This is the key mechanism for supporting long novels:
        1. Extract key events → episodic memory
        2. Extract state changes → semantic memory
        3. Clear working memory for this chapter

        Called after each chapter is finalized.
        """
        logger.info("Compressing chapter %d into memory", chapter_num)

        # Get existing semantic context for reference
        semantic_ctx = self.semantic.to_context(limit=20)

        prompt = (
            "你是记忆管理器。请从以下章节内容中提取两类信息：\n\n"
            "【章节内容】\n"
            f"{_truncate(chapter_text, 8000)}\n\n"
            "【已有世界知识】\n"
            f"{semantic_ctx}\n\n"
            "请输出 JSON 格式：\n"
            "{\n"
            '  "events": ["事件1：简短描述", "事件2：简短描述", ...],\n'
            '  "state_changes": [\n'
            '    {"entity": "角色/地点名", "change": "状态变化描述", "importance": 1-10}\n'
            "  ]\n"
            "}\n"
            "每条 event ≤30字，state_change ≤40字。只保留关键信息。"
        )

        resp = self.llm.chat(system="", user=prompt, temperature=0.2, enable_thinking=False)
        parsed = _safe_json(resp.content)

        # Store events as episodic memory
        for i, event in enumerate(parsed.get("events", [])):
            self.add_episodic(
                key=f"ch{chapter_num}_event_{i}",
                content=event,
                chapter=chapter_num,
                importance=6,
                tags=["event", f"ch{chapter_num}"],
            )

        # Store state changes as semantic memory
        for change in parsed.get("state_changes", []):
            entity = change.get("entity", "unknown")
            safe_entity = entity.replace(" ", "_")[:20]
            self.add_semantic(
                key=f"state_{safe_entity}_{chapter_num}",
                content=f"{entity}: {change.get('change', '')}",
                importance=change.get("importance", 5),
                tags=["state", entity, f"ch{chapter_num}"],
            )

        # Clear working memory for this chapter
        working_keys = [
            e.key for e in self.working.get_all()
            if e.chapter == chapter_num
        ]
        for key in working_keys:
            self.working.remove(key)

    def get_context_for_writing(self, chapter_num: int) -> str:
        """Assemble memory context for writing a specific chapter.

        Retrieval strategy (inspired by Generative Agents):
        1. Recent episodic memories (last 3 chapters)
        2. High-importance semantic memories (character states, world rules)
        3. Current working memory
        """
        sections = []

        # Working memory
        working = self.working.to_context()
        if working != "（无记录）":
            sections.append(f"【工作记忆（当前上下文）】\n{working}")

        # Recent episodic memories (last 3 chapters)
        recent_episodes = []
        for ch in range(max(1, chapter_num - 3), chapter_num):
            episodes = self.episodic.search(chapter=ch, limit=5)
            for e in episodes:
                recent_episodes.append(f"[CH{ch}] {e.content}")
        if recent_episodes:
            sections.append(f"【近期事件回顾】\n" + "\n".join(f"- {e}" for e in recent_episodes))

        # Important semantic memories (character states, world facts)
        semantic = self.semantic.search(min_importance=5, limit=15)
        if semantic:
            sem_lines = [f"- {e.content}" for e in semantic]
            sections.append(f"【世界知识与角色状态】\n" + "\n".join(sem_lines))

        return "\n\n".join(sections) if sections else "（尚无记忆）"

    def get_character_states(self) -> list[MemoryEntry]:
        """Get all character-related semantic memories."""
        return self.semantic.search(tags=["state"], limit=50)

    def get_chapter_summary(self, chapter_num: int) -> str:
        """Get a summary of events for a specific chapter."""
        episodes = self.episodic.search(chapter=chapter_num, limit=10)
        if not episodes:
            return f"（第{chapter_num}章无记录）"
        return "\n".join(f"- {e.content}" for e in episodes)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _safe_json(text: str) -> dict:
    """Parse JSON from LLM output, handling markdown code blocks."""
    import json
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}
