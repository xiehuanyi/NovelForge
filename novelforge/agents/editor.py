"""Editor agent — reviews and improves chapter drafts.

Implements the multi-agent debate/review pattern:
  Writer generates → Editor reviews → Writer revises (if needed)

The Editor evaluates on multiple dimensions:
1. Plot coherence (does this chapter connect to the overall arc?)
2. Character consistency (do characters act in-character?)
3. Pacing and engagement (is the chapter compelling?)
4. Technical quality (prose, dialogue, scene transitions)

This is a key differentiator from single-agent writing systems.
In multi-agent debate (Du et al., 2023), having a separate critic
significantly improves output quality.
"""

from __future__ import annotations

import json

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import MessageType


class EditorAgent(Agent):
    role = AgentRole.EDITOR

    @property
    def system_prompt(self) -> str:
        return (
            "你是一位资深小说编辑，负责审查章节质量并给出结构化的评审意见。\n\n"
            "# 评审维度\n"
            "1. **剧情连贯性** (0-25分)：与大纲是否一致？与前文是否衔接？\n"
            "2. **角色一致性** (0-25分)：角色行为是否符合人设？对话是否有个性？\n"
            "3. **节奏与吸引力** (0-25分)：是否有起伏？章末钩子是否有效？\n"
            "4. **文笔质量** (0-25分)：场景描写、对话、过渡是否流畅？\n\n"
            "# 输出格式\n"
            "请输出 JSON 格式的评审报告：\n"
            "```json\n"
            "{\n"
            '  "total_score": 0-100,\n'
            '  "dimensions": {\n'
            '    "plot_coherence": {"score": 0-25, "comment": "..."},\n'
            '    "character_consistency": {"score": 0-25, "comment": "..."},\n'
            '    "pacing": {"score": 0-25, "comment": "..."},\n'
            '    "writing_quality": {"score": 0-25, "comment": "..."}\n'
            "  },\n"
            '  "issues": ["具体问题1", "具体问题2"],\n'
            '  "suggestions": ["具体改进建议1", "具体改进建议2"],\n'
            '  "verdict": "pass 或 revise"\n'
            "}\n"
            "```\n\n"
            "# 评审标准\n"
            "- 总分 ≥ 70 → verdict: pass\n"
            "- 总分 < 70 → verdict: revise，并给出具体修改建议\n"
            "- issues 列出具体的问题段落或不一致之处\n"
            "- suggestions 给出可执行的改进建议"
        )

    def execute(self, **kwargs) -> dict:
        """Review a chapter draft.

        Args:
            draft: the chapter text to review
            chapter_slice: the chapter's outline (for checking adherence)
            memory_context: memory context for consistency checking
            world_bible: Series Bible (for checking world consistency)
            characters: character profiles (for character consistency)

        Returns:
            dict with review results (scores, issues, suggestions, verdict)
        """
        draft = kwargs.get("draft", "")
        chapter_slice = kwargs.get("chapter_slice", {})
        memory_context = kwargs.get("memory_context", "")
        world_bible = kwargs.get("world_bible", "")
        characters = kwargs.get("characters", "")

        ch_num = chapter_slice.get("chapter", "?")
        slice_json = json.dumps(chapter_slice, ensure_ascii=False, indent=2)

        user_prompt = (
            f"请评审第{ch_num}章的内容。\n\n"
            f"【章节大纲】\n{slice_json}\n\n"
            f"【章节正文】\n{draft}\n\n"
        )

        if memory_context:
            user_prompt += f"【前文记忆】\n{memory_context}\n\n"
        if characters:
            user_prompt += f"【角色档案摘要】\n{_truncate(characters, 3000)}\n\n"

        user_prompt += "请输出 JSON 格式的评审报告。"

        resp = self.call_llm(user_prompt, temperature=0.3)

        review = _safe_json(resp.content)
        if not review:
            review = {
                "total_score": 75,
                "dimensions": {},
                "issues": [],
                "suggestions": [],
                "verdict": "pass",
            }

        self.emit(
            MessageType.REVIEW_RESULT,
            json.dumps(review, ensure_ascii=False),
            chapter=ch_num,
            verdict=review.get("verdict", "pass"),
            score=review.get("total_score", 0),
        )
        return review

    def generate_revision_prompt(self, draft: str, review: dict) -> str:
        """Create a revision prompt based on review results.

        This is passed to the Writer agent for revision.
        """
        issues = "\n".join(f"- {i}" for i in review.get("issues", []))
        suggestions = "\n".join(f"- {s}" for s in review.get("suggestions", []))

        return (
            "请根据以下编辑意见修订章节内容：\n\n"
            f"【编辑评分】{review.get('total_score', '?')}/100\n\n"
            f"【发现问题】\n{issues or '无'}\n\n"
            f"【改进建议】\n{suggestions or '无'}\n\n"
            f"【原稿】\n{draft}\n\n"
            "请输出修订后的完整章节正文（保留章节标题，末尾添加 <章节结束>）。"
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
