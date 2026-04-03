"""Outliner agent — generates chapter-by-chapter outline with scene breakdowns.

Combines the roles of the original "weaver" and "slicer" into a single
two-pass process:
1. First pass: generate high-level chapter outline (chapter titles + summaries)
2. Second pass: break each chapter into detailed scene slices

This two-pass design prevents information loss that occurs when
outline and slicing are done by different agents.
"""

from __future__ import annotations

import json
from typing import Optional

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import MessageType


class OutlinerAgent(Agent):
    role = AgentRole.OUTLINER

    @property
    def system_prompt(self) -> str:
        return (
            "你是「章节编剧」，擅长将世界观和角色设定转化为可执行的章节计划。\n\n"
            "# 核心原则\n"
            "- 每一章都必须有「推进点」（plot advancement）\n"
            "- 每一章结尾都必须有「钩子」（让读者想继续读）\n"
            "- 节奏遵循：铺垫 → 升级 → 转折 → 高潮 → 收束\n"
            "- 伏笔必须在计划中标注埋设和回收位置\n\n"
            "# 约束\n"
            "- 必须覆盖所有章节，不能遗漏\n"
            "- 每章 3-5 个场景\n"
            "- 场景描述要具体到：地点 + 事件 + 冲突 + 参与角色\n"
            "- 输出纯 JSON（不要用代码块标记），每行一个 JSON 对象（JSONL格式）"
        )

    def execute(self, **kwargs) -> str:
        """Generate the full chapter outline.

        Args:
            world_bible: Series Bible text
            characters: character profiles text
            extra: additional instructions
        """
        world_bible = kwargs.get("world_bible", "")
        characters = kwargs.get("characters", "")
        extra = kwargs.get("extra", "")
        spec = self.config.novel

        user_prompt = (
            f"{spec.to_context()}\n\n"
            f"【Series Bible】\n{world_bible}\n\n"
            f"【角色档案】\n{characters}\n\n"
        )
        if extra:
            user_prompt += f"【补充要求】\n{extra}\n\n"

        user_prompt += (
            f"请输出第1章到第{spec.chapters}章的详细目录。\n"
            "每章一行 JSON，格式如下：\n"
            '{"chapter": 1, "title": "章节标题", "summary": "1-2句梗概", '
            '"phase": "开端/发展/转折/高潮/收束", '
            '"scenes": ["场景1：地点-事件-冲突-角色", "场景2：..."], '
            '"hook": "章末悬念", '
            '"focus_characters": ["角色A", "角色B"], '
            '"foreshadowing": "本章埋设或回收的伏笔（可选）", '
            f'"word_target": {spec.chapter_words}}}\n\n'
            f"总共{spec.chapters}章，每章一行JSON，不要遗漏。"
        )

        resp = self.call_llm(user_prompt, temperature=0.7)
        result = resp.content

        self.emit(MessageType.OUTLINE, result)
        return result

    def get_chapter_slice(self, outline_text: str, chapter_num: int) -> Optional[dict]:
        """Extract a specific chapter's outline from the JSONL text."""
        for line in outline_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("chapter") == chapter_num:
                    return obj
            except json.JSONDecodeError:
                continue
        return None

    def parse_outline(self, outline_text: str) -> list[dict]:
        """Parse the full JSONL outline into a list of chapter objects."""
        chapters = []
        for line in outline_text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                chapters.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return sorted(chapters, key=lambda c: c.get("chapter", 0))
