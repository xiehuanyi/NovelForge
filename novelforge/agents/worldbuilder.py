"""WorldBuilder agent — generates the Series Bible (world setting document).

The Series Bible is the foundation of the entire novel. It defines:
- Core premise and logline
- World rules and power systems
- Thematic structure (acts/phases)
- Planted foreshadowing threads

This agent runs once at the start of the pipeline, but can be invoked
again for revisions based on user feedback.
"""

from __future__ import annotations

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import MessageType


class WorldBuilderAgent(Agent):
    role = AgentRole.WORLDBUILDER

    @property
    def system_prompt(self) -> str:
        return (
            "你是「系列小说架构师」，专精于中长篇小说的世界观构建和整体结构设计。\n\n"
            "# 核心能力\n"
            "你擅长将一个模糊的灵感转化为可落地的创作蓝图（Series Bible）。\n\n"
            "# 输出要求\n"
            "请按以下结构输出 Series Bible：\n\n"
            "## 1. 基础信息\n"
            "- 【书名】（若用户未提供则拟定）\n"
            "- 【核心Logline】一句话概括\n"
            "- 【题材/类型】\n"
            "- 【目标读者】\n\n"
            "## 2. 主题与卖点\n"
            "- 核心主题\n"
            "- 核心卖点（3个）\n"
            "- 读者爽点\n\n"
            "## 3. 世界观设定\n"
            "- 时空背景\n"
            "- 核心规则/力量体系（3-5层）\n"
            "- 社会结构\n"
            "- 关键地点（3-5个）\n\n"
            "## 4. 结构节奏\n"
            "- 分为 3-5 个阶段（开端/发展/转折/高潮/收束）\n"
            "- 每个阶段的核心事件和情感走向\n\n"
            "## 5. 伏笔规划\n"
            "- 至少 3 条可回收的伏笔线\n"
            "- 每条标注：埋设位置 → 回收位置\n\n"
            "## 6. 风格基调\n"
            "- 叙事视角\n"
            "- 语言风格\n"
            "- 情感基调\n\n"
            "# 约束\n"
            "- 避免过度宏大的设定，强调「可写性」\n"
            "- 所有设定必须服务于故事推进\n"
            "- 保持内部一致性"
        )

    def execute(self, **kwargs) -> str:
        """Generate the Series Bible.

        Args:
            idea: user's creative idea/inspiration
            extra: additional instructions from user
        """
        idea = kwargs.get("idea", "")
        extra = kwargs.get("extra", "")
        spec = self.config.novel

        user_prompt = (
            f"{spec.to_context()}\n\n"
            f"【用户灵感】\n{idea}\n\n"
        )
        if extra:
            user_prompt += f"【补充要求】\n{extra}\n\n"
        user_prompt += "请生成完整的 Series Bible。"

        resp = self.call_llm(user_prompt, temperature=0.8)
        result = resp.content

        # Self-reflection if enabled
        if self.config.pipeline.enable_self_reflection:
            result = self.self_reflect(
                result,
                criteria=(
                    "1. 世界观是否内部一致？\n"
                    "2. 结构是否覆盖了完整的叙事弧线？\n"
                    "3. 伏笔是否有明确的埋设和回收点？\n"
                    "4. 设定是否过度膨胀（超出可写范围）？"
                ),
            )

        self.emit(MessageType.WORLD_BIBLE, result)
        return result
