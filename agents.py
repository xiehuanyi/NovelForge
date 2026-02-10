from dataclasses import dataclass
from typing import Dict, List


@dataclass
class AgentProfile:
    agent_id: str
    name: str
    description: str
    color: str
    prompt_file: str
    hidden: bool = False


GUIDE_MESSAGE = "欢迎来到 Novel Agents。请用一句话告诉我你的创作灵感："


AGENTS: List[AgentProfile] = [
    AgentProfile(
        agent_id="guide",
        name="主持人",
        description="项目引导与使用说明（固定介绍）",
        color="#f7c36f",
        prompt_file="",
        hidden=False,
    ),
    AgentProfile(
        agent_id="architect",
        name="架构师",
        description="输出 Series Bible（全书蓝图）",
        color="#f08a5d",
        prompt_file="architect.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="intent",
        name="需求解析",
        description="把灵感整理成结构化需求",
        color="#2a9d8f",
        prompt_file="intent.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="profiler",
        name="角色设计",
        description="输出角色系统与关系网",
        color="#6a8caf",
        prompt_file="profiler.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="weaver",
        name="编剧",
        description="生成章节目录（JSONL）",
        color="#3da5d9",
        prompt_file="weaver.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="writer",
        name="写手",
        description="按切片写章节正文",
        color="#d1495b",
        prompt_file="writer.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="checker",
        name="格式检查",
        description="只看格式与完整性",
        color="#2a9d8f",
        prompt_file="checker.txt",
        hidden=False,
    ),
    AgentProfile(
        agent_id="slicer",
        name="切片师",
        description="拆分章节切片（后台）",
        color="#ff9f1c",
        prompt_file="slicer.txt",
        hidden=True,
    ),
    AgentProfile(
        agent_id="memory",
        name="记忆压缩",
        description="更新短中长期记忆（后台）",
        color="#8d99ae",
        prompt_file="memory.txt",
        hidden=True,
    ),
]


def agent_map() -> Dict[str, AgentProfile]:
    return {agent.agent_id: agent for agent in AGENTS}
