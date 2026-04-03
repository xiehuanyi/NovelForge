"""Writer agent — generates chapter prose from outline slices.

The Writer is the most frequently called agent, running once per chapter.
It receives:
- The chapter's scene breakdown (from Outliner)
- Memory context (from MemoryManager)
- The tail of the previous chapter (for continuity)

Key design decisions:
- Temperature is higher (0.85) for creative writing
- The writer strictly follows the scene order from the outline
- Output ends with <章节结束> marker for clean parsing
"""

from __future__ import annotations

import json

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import MessageType


class WriterAgent(Agent):
    role = AgentRole.WRITER

    @property
    def system_prompt(self) -> str:
        return (
            "你是一位资深网文写手，擅长中长篇小说创作。\n\n"
            "# 写作准则\n"
            "1. 严格按照场景列表（scenes）顺序写作，不跳过任何场景\n"
            "2. 必须完成章末悬念（hook）\n"
            "3. 字数控制在目标字数 ±15% 范围内\n"
            "4. 开头输出章节标题（如：第X章 标题），空一行后写正文\n"
            "5. 正文结束后添加 `<章节结束>` 标记\n\n"
            "# 写作技巧\n"
            "- 场景转换要自然，用环境描写或角色行为过渡\n"
            "- 对话要有角色个性，避免所有人说话方式相同\n"
            "- 用具体细节代替抽象描述（「他握紧了拳」 > 「他很愤怒」）\n"
            "- 保持与前文的连贯性（参考【上一章末尾】和【记忆】）\n"
            "- 注意角色状态的一致性（位置、情绪、已知信息）\n\n"
            "# 一致性检查清单（写作时自查）\n"
            "- 角色称呼是否统一？\n"
            "- 角色的已知信息是否与前文一致？\n"
            "- 场景中的时间线是否连贯？\n"
            "- 是否有遗留的伏笔需要呼应？\n\n"
            "# 禁忌\n"
            "- 不要在正文中加入 meta 注释或作者说明\n"
            "- 不要在章节中间突然总结剧情\n"
            "- 不要让角色突然获得不应知道的信息"
        )

    def execute(self, **kwargs) -> str:
        """Write a single chapter.

        Args:
            chapter_slice: dict with chapter outline (scenes, hook, etc.)
            memory_context: assembled memory from MemoryManager
            prev_tail: last ~800 chars of previous chapter
            extra: additional user instructions
        """
        chapter_slice = kwargs.get("chapter_slice", {})
        memory_context = kwargs.get("memory_context", "")
        prev_tail = kwargs.get("prev_tail", "")
        extra = kwargs.get("extra", "")
        spec = self.config.novel

        ch_num = chapter_slice.get("chapter", 1)
        slice_json = json.dumps(chapter_slice, ensure_ascii=False, indent=2)

        user_prompt = (
            f"{spec.to_context()}\n\n"
            f"【章节大纲】\n{slice_json}\n\n"
        )

        if memory_context:
            user_prompt += f"【记忆上下文】\n{memory_context}\n\n"

        if prev_tail:
            user_prompt += f"【上一章末尾】\n{prev_tail}\n\n"

        if extra:
            user_prompt += f"【补充要求】\n{extra}\n\n"

        user_prompt += (
            f"请撰写第{ch_num}章正文。\n"
            f"目标字数：约{chapter_slice.get('word_target', spec.chapter_words)}字。\n"
            "严格按照 scenes 顺序写作，完成 hook，最后添加 <章节结束> 标记。"
        )

        resp = self.call_llm(user_prompt, temperature=0.85)
        result = resp.content

        # Clean up: remove content after <章节结束>
        if "<章节结束>" in result:
            result = result.split("<章节结束>")[0].strip()

        self.emit(
            MessageType.CHAPTER_DRAFT,
            result,
            chapter=ch_num,
            title=chapter_slice.get("title", ""),
        )
        return result
