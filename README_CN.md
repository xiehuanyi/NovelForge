# NovelForge

**多智能体协同小说创作系统**

[English](README.md)

NovelForge 是一个基于多智能体（Multi-Agent）架构的长篇小说自动生成系统。6 个专业 Agent 各司其职，通过消息总线协同工作，支持从灵感到完稿的全流程自动化创作。

```
灵感 --> [世界构建师] --> [角色设计师] --> [大纲编剧] --> [写手] <=> [编辑] --> 完整小说
                                                          |
                                                     [记忆管理器]
```

**规模验证**: 成功生成 400 章、108 万字的长篇玄幻小说，耗时 4.5 小时（见 [`examples/`](examples/)）。

## 核心特性

| 特性 | 说明 |
|------|------|
| **6 Agent 协同** | 世界构建、角色设计、大纲编排、正文写作、审查编辑、记忆管理 |
| **Writer-Editor Debate** | 写手 ↔ 编辑多轮审查，自动修订低分章节 |
| **三层记忆系统** | 工作记忆 / 情节记忆 / 语义记忆，支持无限长度小说 |
| **一致性评估** | 角色一致性、剧情连贯性、世界观一致性量化评分 |
| **Self-Reflection** | Agent 自我审查机制（Reflexion 模式），自动改进输出质量 |
| **百万字长篇** | 分层记忆压缩 + 滑动窗口上下文 |
| **Rich TUI** | 基于 Rich 的交互式终端 UI，实时显示 Agent 活动 |
| **断点续写** | 自动保存进度，中断后可从断点恢复 |

## 快速开始

### 安装

```bash
git clone https://github.com/your-repo/NovelForge.git
cd NovelForge
pip install -r requirements.txt
```

依赖极简，仅 3 个包：`openai`、`rich`、`pydantic`。

### 运行

```bash
# 交互式 TUI 模式（默认）
python main.py

# 指定 API Key
python main.py --api-key sk-your-key

# 无头模式（脚本/批量使用）
python main.py --headless

# 恢复已有项目
python main.py --resume my_novel
```

### TUI 命令

```
NovelForge> run             运行完整生成流程
NovelForge> status          查看项目状态
NovelForge> chapter 3       查看第 3 章
NovelForge> bible           查看 Series Bible
NovelForge> characters      查看角色档案
NovelForge> outline         查看章节大纲
NovelForge> review 5        查看第 5 章的编辑评审
NovelForge> consistency 3   对第 3 章运行一致性检查
NovelForge> memory          查看三层记忆状态
NovelForge> export          导出完整小说
NovelForge> config          查看/修改配置
NovelForge> help            显示帮助
NovelForge> quit            退出
```

## 系统架构

### 整体架构

```
+------------------------------------------------------------------+
|                        Orchestrator                               |
|                 中央控制器，管理 Agent 执行顺序                      |
+------------+------------+----------+-----------+---------+--------+
| WorldBuilder | Character | Outliner |  Writer   | Editor  |
+------+-------+-----+----+-----+----+-----+-----+----+----+
       |             |          |          |          |
       +-------------+----------+----------+----------+
                              |
                      +-------+-------+
                      |  Message Bus  |  <-- 发布/订阅 + 黑板
                      +-------+-------+
                              |
                +-------------+-------------+
                |             |             |
          +-----+-----+ +----+----+ +------+------+
          |  Working   | | Episodic| |  Semantic   |
          |  Memory    | | Memory  | |  Memory     |
          | (工作记忆) | |(情节)   | | (语义)      |
          +------------+ +---------+ +-------------+
```

### Agent 角色与职责

| Agent | 职责 | 输入 | 输出 |
|-------|------|------|------|
| **WorldBuilder** | 生成 Series Bible（世界观/结构/主题） | 用户灵感 + 小说规格 | 世界观文档 |
| **Character** | 创建角色档案 + 关系网 + 初始状态 | Series Bible | 角色档案 + 状态表 |
| **Outliner** | 编排章节目录 + 场景切片 | Bible + 角色 | JSONL 章节大纲 |
| **Writer** | 撰写单章正文 | 大纲 + 记忆 + 前文 | 章节正文 |
| **Editor** | 多维度评审（4轴，0-100分） | 正文 + 大纲 + 角色 | 评分 + 修改建议 |
| **MemoryManager** | 压缩章节内容为结构化记忆 | 章节正文 | 事件记录 + 状态更新 |

### 通信模式

系统实现了三种经典的多智能体通信模式：

```python
# 1. 直接消息 -- Agent A -> Agent B
bus.send(Message(sender="writer", receiver="editor", ...))

# 2. 广播 -- Agent A -> 全体
bus.broadcast(Message(sender="orchestrator", ...))

# 3. 黑板 -- 共享状态
bus.blackboard["world_bible"] = bible_text  # 任何 Agent 可读写
```

### Writer-Editor Debate Loop

```
+-----------+     初稿      +-----------+
|           | ------------> |           |
|   Writer  |               |  Editor   |
|           | <------------ |           |
|           |    评审报告    |           |
|           |  (score < 70?)|           |
|           |               |           |
|   修订稿  | ------------> |  再次评审  |
|           |               |           |
+-----------+               +-----------+
      | (通过)
  保存 + 更新记忆
```

实现了 **Multi-Agent Debate** 模式（Du et al., 2023），通过独立 Critic Agent 显著提升输出质量。

### 三层记忆系统

```
+-----------------------------------------------+
|         Working Memory (工作记忆)               |
|  当前章节上下文，每章结束后压缩到情节记忆           |
+-----------------------------------------------+
|         Episodic Memory (情节记忆)              |
|  章节级事件记录，按时间排序                       |
|  例: "第3章: 主角发现秘密实验室"                  |
+-----------------------------------------------+
|         Semantic Memory (语义记忆)              |
|  持久事实: 角色状态、世界规则、关系变化             |
|  例: "林渊: 位于封神殿, 已觉醒逆封之力"           |
+-----------------------------------------------+
```

**灵感来源**:
- [Generative Agents](https://arxiv.org/abs/2304.03442)（Park et al., 2023）— 重要性评分 + 时间衰减检索
- [MemGPT](https://arxiv.org/abs/2310.08560)（Packer et al., 2023）— 分层内存自动迁移
- Claude Code — 基于文件的持久化记忆 + 结构化索引

**为什么不用向量数据库？**
- 依赖最小化（不需要 ChromaDB/Faiss）
- 记忆内容可直接阅读和调试（JSON 文件）
- 小说创作场景下，基于标签/章节号的检索比向量相似度更精确

### 一致性评估系统

三个维度，每个 0-100 分：

| 维度 | 检查内容 |
|------|----------|
| **角色一致性** | 行为是否符合人设？对话是否有个性？知识是否前后矛盾？ |
| **剧情一致性** | 与大纲是否吻合？因果链是否合理？伏笔是否回收？ |
| **世界观一致性** | 是否违反已建立的规则？地理/时间线是否合理？ |

方法：**LLM-as-Judge**，将章节内容与记忆系统中的已知状态进行对比。

## 项目结构

```
NovelForge/
├── main.py                      # 入口: TUI / Headless
├── requirements.txt             # 依赖 (仅 3 个包)
├── novelforge/                  # 主包
│   ├── core/                    # 核心抽象
│   │   ├── agent.py             #   Agent 基类 + AgentRole
│   │   ├── message.py           #   消息类型 + MessageBus
│   │   ├── llm.py               #   LLM 客户端 (OpenAI 兼容)
│   │   └── config.py            #   配置数据类
│   ├── agents/                  # Agent 实现
│   │   ├── orchestrator.py      #   中央协调器
│   │   ├── worldbuilder.py      #   世界构建师
│   │   ├── character.py         #   角色设计师
│   │   ├── outliner.py          #   大纲编剧
│   │   ├── writer.py            #   写手
│   │   └── editor.py            #   编辑
│   ├── memory/                  # 记忆子系统
│   │   ├── base.py              #   MemoryStore (文件持久化)
│   │   └── manager.py           #   MemoryManager (三层管理)
│   ├── evaluation/              # 评估系统
│   │   └── consistency.py       #   一致性检查器
│   └── tui/                     # 终端界面
│       └── app.py               #   Rich TUI
├── examples/                    # 示例输出 (108万字长篇)
└── output/                      # 生成产物 (gitignored)
```

## 技术亮点

### 1. 三种 Agent 通信范式

| 模式 | 实现 | 适用场景 |
|------|------|----------|
| Pipeline | Orchestrator 按序调用 | 主流程 (构建 -> 设计 -> 大纲 -> 写作) |
| Debate | Writer <-> Editor 多轮审查 | 质量保证 (生成 -> 评审 -> 修订) |
| Blackboard | MessageBus.blackboard | 共享状态 (世界观、角色状态) |

### 2. Self-Reflection (Reflexion 模式)

每个 Agent 内置 `self_reflect()` 方法：生成 -> 自我审查 -> 修订。实现了 **Reflexion**（Shinn et al., 2023）的核心思想。

### 3. 长文本生成策略

百万字长篇的关键：不把所有前文塞进上下文，而是通过记忆系统提取关键信息。

```
写作时的上下文组成:
+---------------------------------------+
| 小说规格           (~200 tokens)      |
| 章节大纲           (~500 tokens)      |
| 记忆上下文:                           |
|   工作记忆         (~1k tokens)       |
|   近期事件         (~1k tokens)       |
|   语义记忆         (~1k tokens)       |
| 上一章末尾         (~500 tokens)      |
| 系统提示           (~1k tokens)       |
+---------------------------------------+
总计 ~5-6k tokens << 128k 窗口
```

### 4. Orchestrator vs 去中心化

| 方面 | Orchestrator | 去中心化 |
|------|-------------|---------|
| 可调试性 | 流程清晰可追踪 | 难以追踪 |
| 可靠性 | 失败点明确 | 级联故障 |
| 灵活性 | 流程较固定 | 高度灵活 |
| 适用 | Pipeline 型任务 | 开放式对话 |

小说创作是 Pipeline 型任务，Orchestrator 更合适。

## Q&A

### Q: 为什么用多 Agent 而不是单一大模型？

1. **关注点分离**：每个 Agent 有专属系统提示，可以深度优化。
2. **质量保证**：Writer-Editor 分离实现了「生成-批评」分离，独立 Critic 比自我评估更有效。
3. **可维护性**：独立调整单个 Agent 的提示词和参数，不影响其他 Agent。

### Q: 记忆系统和 RAG 有什么区别？

本质上是**轻量级、领域特化的 RAG**：
- 用结构化标签（章节号、角色名、重要性分数）代替向量嵌入
- 三层分级（working/episodic/semantic），RAG 通常是扁平的
- 有主动的压缩和迁移机制（working -> episodic -> semantic）

小说创作中，基于标签的精确检索比向量相似度更可靠。

### Q: 如何保证角色一致性？

三层防线：
1. **初始状态表**：Character Agent 输出结构化初始状态（JSON），存入语义记忆
2. **记忆追踪**：每章结束后提取角色状态变化，更新语义记忆
3. **一致性检查**：ConsistencyChecker 对比当前章节与记忆中的角色状态

### Q: 系统的瓶颈在哪？

**延迟**：每章需 3-5 次 LLM 调用。50 章小说 = 150-250 次 API 调用。可通过并行生成和减少审查轮次优化。

**质量上限**：情感细腻度受限于基础模型，长期伏笔的埋设和回收依赖大纲质量。

## 模型配置

默认使用阿里云百炼的 `qwen3.5-flash`（128K 上下文）。基于 OpenAI 兼容协议，可轻松切换模型：

```python
LLMConfig(
    model="qwen3.5-flash",
    base_url="https://...",
    api_key="sk-...",
    max_tokens=16384,
    context_window=131072,
    enable_thinking=True,
)
```

## 参考文献

- Park, J.S. et al. (2023). [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
- Du, Y. et al. (2023). [Improving Factuality and Reasoning through Multiagent Debate](https://arxiv.org/abs/2305.14325)
- Shinn, N. et al. (2023). [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- Packer, C. et al. (2023). [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- Hong, S. et al. (2023). [MetaGPT: Meta Programming for Multi-Agent Collaborative Framework](https://arxiv.org/abs/2308.00352)
- Qian, C. et al. (2023). [ChatDev: Communicative Agents for Software Development](https://arxiv.org/abs/2307.07924)

## License

MIT
