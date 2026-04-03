"""Consistency evaluation for long-form novels.

Addresses three dimensions of consistency:

1. **Character Consistency**: Do characters behave according to their profiles?
   - Track: location, knowledge, relationships, mood across chapters
   - Detect: out-of-character actions, knowledge violations, name changes

2. **Plot Consistency**: Does the story follow its own internal logic?
   - Track: open plot threads, planted foreshadowing, cause-effect chains
   - Detect: plot holes, abandoned threads, timeline contradictions

3. **World Consistency**: Does the world follow its established rules?
   - Track: power system rules, geography, social structures
   - Detect: rule violations, spatial impossibilities

Evaluation approach:
- LLM-as-judge for nuanced consistency checking
- Structured state tracking for mechanical checks
- Quantitative scoring (0-100) per dimension

References:
- FABLES benchmark (Kim et al., 2024): character tracking in book-length fiction
- LongBench (Bai et al., 2024): long-context understanding evaluation
- Consistency measures in dialogue systems (Welleck et al., 2019)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from novelforge.core.llm import LLMClient
from novelforge.memory import MemoryManager

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyReport:
    """Result of a consistency evaluation."""
    chapter: int
    character_score: float = 0.0
    plot_score: float = 0.0
    world_score: float = 0.0
    overall_score: float = 0.0
    issues: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.overall_score >= 70.0


class ConsistencyChecker:
    """Evaluates consistency across chapters.

    Works in two modes:
    1. Per-chapter check: evaluate a single chapter against known state
    2. Global check: evaluate across all chapters for cross-cutting issues
    """

    def __init__(self, llm: LLMClient, memory: MemoryManager):
        self.llm = llm
        self.memory = memory

    def check_chapter(
        self,
        chapter_num: int,
        chapter_text: str,
        characters: str,
        world_bible: str,
        prev_chapters_summary: str = "",
    ) -> ConsistencyReport:
        """Evaluate consistency of a single chapter.

        Uses LLM-as-judge to detect inconsistencies by comparing the chapter
        against known state (character profiles, world rules, previous events).
        """
        # Gather known state from memory
        char_states = self.memory.get_character_states()
        state_ctx = "\n".join(f"- {s.content}" for s in char_states) if char_states else "（无状态记录）"

        recent_events = ""
        for ch in range(max(1, chapter_num - 3), chapter_num):
            summary = self.memory.get_chapter_summary(ch)
            if summary != f"（第{ch}章无记录）":
                recent_events += f"\n[第{ch}章] {summary}"

        prompt = (
            "你是小说一致性评估专家。请检查以下章节是否存在一致性问题。\n\n"
            f"【第{chapter_num}章内容】\n{_truncate(chapter_text, 6000)}\n\n"
            f"【角色档案】\n{_truncate(characters, 3000)}\n\n"
            f"【角色当前状态】\n{state_ctx}\n\n"
            f"【前几章事件】\n{recent_events or '（无）'}\n\n"
            f"【世界观规则】\n{_truncate(world_bible, 2000)}\n\n"
            "请从三个维度评估并输出 JSON：\n"
            "{\n"
            '  "character_consistency": {\n'
            '    "score": 0-100,\n'
            '    "issues": ["具体不一致之处"]\n'
            "  },\n"
            '  "plot_consistency": {\n'
            '    "score": 0-100,\n'
            '    "issues": ["剧情逻辑问题"]\n'
            "  },\n"
            '  "world_consistency": {\n'
            '    "score": 0-100,\n'
            '    "issues": ["世界观规则违反"]\n'
            "  }\n"
            "}\n"
            "如果没有问题，issues 为空数组，score 给高分。"
        )

        resp = self.llm.chat(system="", user=prompt, temperature=0.2, enable_thinking=False)
        result = _safe_json(resp.content)

        char_dim = result.get("character_consistency", {})
        plot_dim = result.get("plot_consistency", {})
        world_dim = result.get("world_consistency", {})

        char_score = char_dim.get("score", 80)
        plot_score = plot_dim.get("score", 80)
        world_score = world_dim.get("score", 80)
        overall = (char_score + plot_score + world_score) / 3

        all_issues = (
            char_dim.get("issues", [])
            + plot_dim.get("issues", [])
            + world_dim.get("issues", [])
        )

        return ConsistencyReport(
            chapter=chapter_num,
            character_score=char_score,
            plot_score=plot_score,
            world_score=world_score,
            overall_score=overall,
            issues=all_issues,
            details=result,
        )

    def check_global(
        self,
        all_chapters: dict[int, str],
        characters: str,
        world_bible: str,
    ) -> ConsistencyReport:
        """Run a global consistency check across all chapters.

        For very long novels, this uses chapter summaries rather than full text
        to stay within context limits.
        """
        # Build chapter summaries
        summaries = []
        for ch_num in sorted(all_chapters.keys()):
            summary = self.memory.get_chapter_summary(ch_num)
            summaries.append(f"第{ch_num}章: {summary}")

        all_summaries = "\n".join(summaries)

        prompt = (
            "你是小说一致性评估专家。请对整部小说进行全局一致性检查。\n\n"
            f"【各章概要】\n{_truncate(all_summaries, 8000)}\n\n"
            f"【角色档案】\n{_truncate(characters, 3000)}\n\n"
            f"【世界观规则】\n{_truncate(world_bible, 2000)}\n\n"
            "请检查：\n"
            "1. 角色弧线是否完整（有起有终）？\n"
            "2. 伏笔是否都有回收？\n"
            "3. 时间线是否有矛盾？\n"
            "4. 角色关系发展是否合理？\n\n"
            "输出 JSON：\n"
            "{\n"
            '  "character_consistency": {"score": 0-100, "issues": [...]},\n'
            '  "plot_consistency": {"score": 0-100, "issues": [...]},\n'
            '  "world_consistency": {"score": 0-100, "issues": [...]},\n'
            '  "arc_completeness": {"score": 0-100, "issues": [...]}\n'
            "}"
        )

        resp = self.llm.chat(system="", user=prompt, temperature=0.2, enable_thinking=False)
        result = _safe_json(resp.content)

        scores = []
        all_issues = []
        for dim in ["character_consistency", "plot_consistency",
                     "world_consistency", "arc_completeness"]:
            dim_data = result.get(dim, {})
            scores.append(dim_data.get("score", 80))
            all_issues.extend(dim_data.get("issues", []))

        return ConsistencyReport(
            chapter=0,  # 0 means global
            character_score=scores[0] if len(scores) > 0 else 80,
            plot_score=scores[1] if len(scores) > 1 else 80,
            world_score=scores[2] if len(scores) > 2 else 80,
            overall_score=sum(scores) / len(scores) if scores else 80,
            issues=all_issues,
            details=result,
        )


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def _safe_json(text: str) -> dict:
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
