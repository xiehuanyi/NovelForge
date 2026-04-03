"""Character Designer agent — creates character profiles and relationship networks.

Key interview talking points:
- Character consistency is one of the hardest problems in long-form generation
- We track character "state" (location, knowledge, relationships) across chapters
- Each character has a structured profile that serves as a "contract" for the writer
"""

from __future__ import annotations

from novelforge.core.agent import Agent, AgentRole
from novelforge.core.message import MessageType


class CharacterAgent(Agent):
    role = AgentRole.CHARACTER

    @property
    def system_prompt(self) -> str:
        return (
            "你是「角色系统设计师」，擅长创造有深度、有弧光的角色群像。\n\n"
            "# 核心原则\n"
            "- 每个角色都必须有清晰的「想要」和「需要」（Want vs Need）\n"
            "- 角色之间必须形成张力网络（合作/对立/误解/秘密）\n"
            "- 角色弧线必须与主题呼应\n\n"
            "# 输出格式\n\n"
            "## 主角团（3-5名）\n"
            "每个角色包含：\n"
            "- 姓名 | 身份\n"
            "- 外在目标（Want）\n"
            "- 内在需求（Need）\n"
            "- 核心动机\n"
            "- 致命弱点/恐惧\n"
            "- 角色弧线：起点状态 → 终点状态\n"
            "- 标志性特征（外貌/口头禅/习惯）\n"
            "- 关键道具或技能\n\n"
            "## 反派/对立阵营（1-3名）\n"
            "（同上格式，反派也需要合理动机）\n\n"
            "## 关键配角（2-4名）\n"
            "（简化格式，但需标明与主角的关系）\n\n"
            "## 关系网络\n"
            "用 A ↔ B 格式列出核心关系，标注关系类型和张力来源：\n"
            "例：张三 ↔ 李四：师徒（表面），竞争者（内里），伏笔：李四知道张三的秘密\n\n"
            "## 角色初始状态表\n"
            "以JSON格式输出每个角色的初始状态：\n"
            "```json\n"
            '{"characters": [\n'
            '  {"name": "角色名", "location": "初始地点", "mood": "情绪", '
            '"knowledge": ["已知信息"], "relationships": {"角色B": "关系"}}\n'
            "]}\n"
            "```\n\n"
            "# 约束\n"
            "- 角色设定必须服务于剧情，不要有无用装饰\n"
            "- 每个角色必须有至少一个可写的冲突点\n"
            "- 初始状态表是后续一致性追踪的基础，务必准确"
        )

    def execute(self, **kwargs) -> str:
        """Generate character profiles.

        Args:
            world_bible: the Series Bible from WorldBuilder
            extra: additional instructions
        """
        world_bible = kwargs.get("world_bible", "")
        extra = kwargs.get("extra", "")
        spec = self.config.novel

        user_prompt = (
            f"{spec.to_context()}\n\n"
            f"【Series Bible】\n{world_bible}\n\n"
        )
        if extra:
            user_prompt += f"【补充要求】\n{extra}\n\n"
        user_prompt += "请生成完整的角色系统，包含角色档案、关系网和初始状态表。"

        resp = self.call_llm(user_prompt, temperature=0.8)
        result = resp.content

        if self.config.pipeline.enable_self_reflection:
            result = self.self_reflect(
                result,
                criteria=(
                    "1. 每个角色是否都有清晰的 Want 和 Need？\n"
                    "2. 角色之间的关系是否形成张力网络？\n"
                    "3. 是否有角色弧线的起终点？\n"
                    "4. 初始状态表是否完整且格式正确？"
                ),
            )

        self.emit(MessageType.CHARACTER_PROFILES, result)
        return result
