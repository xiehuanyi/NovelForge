# NovelForge

**Multi-Agent Collaborative Novel Writing System**

[中文文档](README_CN.md)

NovelForge is a multi-agent system that automatically generates full-length novels. Six specialized agents collaborate through a message bus, covering the entire pipeline from a one-line idea to a published-ready manuscript.

```
Idea --> [WorldBuilder] --> [Character] --> [Outliner] --> [Writer] <=> [Editor] --> Novel
                                                            |
                                                      [MemoryManager]
```

**Proven at scale**: generated a 400-chapter, 1,080,000-word novel in 4.5 hours (see [`examples/`](examples/)).

## Features

| Feature | Description |
|---------|-------------|
| **6-Agent Pipeline** | WorldBuilder, Character Designer, Outliner, Writer, Editor, Memory Manager |
| **Writer-Editor Debate** | Multi-round review loop: Writer drafts, Editor scores, Writer revises |
| **3-Layer Memory** | Working / Episodic / Semantic memory for unbounded novel length |
| **Consistency Evaluation** | Quantitative scoring on character, plot, and world consistency |
| **Self-Reflection** | Each agent can critique and improve its own output (Reflexion pattern) |
| **Million-Word Support** | Hierarchical memory compression + sliding window context |
| **Rich TUI** | Interactive terminal UI with real-time agent activity display |
| **Resumable** | Auto-saves progress; resume from any checkpoint after interruption |

## Quick Start

### Install

```bash
git clone https://github.com/your-repo/NovelForge.git
cd NovelForge
pip install -r requirements.txt
```

Only 3 dependencies: `openai`, `rich`, `pydantic`.

### Run

```bash
# Interactive TUI (default)
python main.py

# Specify API key
python main.py --api-key sk-your-key

# Headless mode (scripting / batch)
python main.py --headless

# Resume an existing project
python main.py --resume my_novel
```

### TUI Commands

```
NovelForge> run             Run the full generation pipeline
NovelForge> status          Show project status and stats
NovelForge> chapter 3       View chapter 3
NovelForge> bible           View the Series Bible
NovelForge> characters      View character profiles
NovelForge> outline         View chapter outline
NovelForge> review 5        View editor review for chapter 5
NovelForge> consistency 3   Run consistency check on chapter 3
NovelForge> memory          Inspect the 3-layer memory state
NovelForge> export          Export the complete novel to a single file
NovelForge> config          View / modify configuration
NovelForge> help            Show all commands
NovelForge> quit            Exit
```

## Architecture

### System Overview

```
+------------------------------------------------------------------+
|                     Orchestrator                                  |
|              Central controller, manages agent execution          |
+------------+------------+----------+-----------+---------+--------+
| WorldBuilder | Character | Outliner |  Writer   | Editor  |
+------+-------+-----+----+-----+----+-----+-----+----+----+
       |             |          |          |          |
       +-------------+----------+----------+----------+
                              |
                      +-------+-------+
                      |  Message Bus  | <-- pub/sub + blackboard
                      +-------+-------+
                              |
                +-------------+-------------+
                |             |             |
          +-----+-----+ +----+----+ +------+------+
          |  Working   | | Episodic| |  Semantic   |
          |  Memory    | | Memory  | |  Memory     |
          +------------+ +---------+ +-------------+
```

### Agent Roles

| Agent | Responsibility | Input | Output |
|-------|---------------|-------|--------|
| **WorldBuilder** | Generate Series Bible (world, structure, themes) | User idea + novel spec | World document |
| **Character** | Create character profiles + relationship graph + initial states | Series Bible | Character profiles + state table |
| **Outliner** | Plan chapter-by-chapter outline with scene breakdowns | Bible + Characters | JSONL chapter outline |
| **Writer** | Write chapter prose from scene slices | Outline + Memory + Previous tail | Chapter text |
| **Editor** | Multi-dimensional quality review (4 axes, 0-100) | Draft + Outline + Characters | Scores + revision suggestions |
| **MemoryManager** | Compress chapter content into structured memory | Chapter text | Event records + state updates |

### Communication Patterns

The system implements three classic multi-agent communication patterns:

```python
# 1. Direct Messaging -- Agent A -> Agent B
bus.send(Message(sender="writer", receiver="editor", ...))

# 2. Broadcast -- Agent A -> All
bus.broadcast(Message(sender="orchestrator", ...))

# 3. Blackboard -- Shared mutable state
bus.blackboard["world_bible"] = bible_text  # Any agent can read/write
```

### Writer-Editor Debate Loop

```
+-----------+     draft      +-----------+
|           | ------------> |           |
|  Writer   |               |  Editor   |
|           | <------------ |           |
|           |    review      |           |
|           |  (score < 70?) |           |
|           |                |           |
|  revised  | ------------> |  re-review |
|           |               |           |
+-----------+               +-----------+
      | (pass)
  Save + Update Memory
```

This implements the **Multi-Agent Debate** pattern (Du et al., 2023), where an independent critic agent significantly improves output quality.

### 3-Layer Memory System

```
+-----------------------------------------------+
|         Working Memory                        |
|  Current chapter context, cleared after each  |
|  chapter is compressed into episodic memory   |
+-----------------------------------------------+
|         Episodic Memory                       |
|  Chapter-level event records, time-ordered    |
|  e.g. "Ch3: Hero discovers the hidden lab"   |
+-----------------------------------------------+
|         Semantic Memory                       |
|  Persistent facts: character states, world    |
|  rules, relationship changes                  |
|  e.g. "Alice: location=Ruins, mood=resolute" |
+-----------------------------------------------+
```

**Inspiration**:
- [Generative Agents](https://arxiv.org/abs/2304.03442) (Park et al., 2023) -- importance scoring + recency-based retrieval
- [MemGPT](https://arxiv.org/abs/2310.08560) (Packer et al., 2023) -- tiered memory with automatic migration
- Claude Code -- file-based persistent memory with structured index

**Why not a vector database?**
- Minimal dependencies (no ChromaDB / Faiss)
- Memory files are human-readable JSON, easy to debug
- For novel writing, tag-based retrieval (chapter number, character name, importance score) is more precise than embedding similarity

### Consistency Evaluation

Three dimensions, each scored 0-100:

| Dimension | What it checks |
|-----------|---------------|
| **Character Consistency** | Do characters act in-character? Is dialogue distinctive? Any knowledge contradictions? |
| **Plot Consistency** | Does the chapter follow the outline? Are cause-effect chains logical? Are foreshadowing threads resolved? |
| **World Consistency** | Are established rules respected? Are geography and timelines coherent? |

Method: **LLM-as-Judge** -- compares chapter content against known state from the memory system (character states, event records, world rules).

## Project Structure

```
NovelForge/
├── main.py                      # Entry point: TUI / Headless
├── requirements.txt             # Dependencies (only 3 packages)
├── novelforge/                  # Main package
│   ├── core/                    # Core abstractions
│   │   ├── agent.py             #   Agent base class + AgentRole enum
│   │   ├── message.py           #   Message types + MessageBus
│   │   ├── llm.py               #   LLM client (OpenAI-compatible)
│   │   └── config.py            #   Configuration dataclasses
│   ├── agents/                  # Agent implementations
│   │   ├── orchestrator.py      #   Central coordinator
│   │   ├── worldbuilder.py      #   World Builder
│   │   ├── character.py         #   Character Designer
│   │   ├── outliner.py          #   Outliner
│   │   ├── writer.py            #   Writer
│   │   └── editor.py            #   Editor
│   ├── memory/                  # Memory subsystem
│   │   ├── base.py              #   MemoryStore (file persistence)
│   │   └── manager.py           #   MemoryManager (3-layer)
│   ├── evaluation/              # Evaluation system
│   │   └── consistency.py       #   Consistency checker
│   └── tui/                     # Terminal UI
│       └── app.py               #   Rich TUI application
├── examples/                    # Example output (1M-word novel)
│   └── 万域封神/
│       ├── series_bible.txt
│       ├── characters.txt
│       ├── outlines/
│       ├── memory/
│       └── sample_chapters/
└── output/                      # Generated output (gitignored)
```

## Technical Highlights

### 1. Three Agent Communication Paradigms

| Pattern | Implementation | Use Case |
|---------|---------------|----------|
| Pipeline | Orchestrator calls agents sequentially | Main flow (build -> design -> outline -> write) |
| Debate | Writer <-> Editor multi-round review | Quality assurance (generate -> critique -> revise) |
| Blackboard | MessageBus.blackboard | Shared state (world bible, character states) |

### 2. Self-Reflection (Reflexion Pattern)

Every agent has a built-in `self_reflect()` method:
1. Generate initial output
2. Critique it against explicit criteria
3. Revise based on the critique

This implements the core idea of **Reflexion** (Shinn et al., 2023).

### 3. LLM-as-Judge Evaluation

The consistency checker uses the LLM itself as a judge:
- Structured scoring (0-100, multi-dimensional)
- Comparison against known state (not judging in a vacuum)
- Can detect deep logical inconsistencies

### 4. Long-Form Generation Strategy

The core challenge for million-word novels is the context window limit. Our solution:

```
Context composition when writing a chapter:
+---------------------------------------+
| Novel spec          (~200 tokens)     |  <-- fixed
| Chapter outline     (~500 tokens)     |  <-- fixed
| Memory context:                       |
|   Working memory    (~1k tokens)      |  <-- current chapter
|   Recent episodes   (~1k tokens)      |  <-- last 3 chapters
|   Semantic memory   (~1k tokens)      |  <-- high-importance facts
| Previous chapter tail (~500 tokens)   |  <-- continuity
| System prompt       (~1k tokens)      |  <-- fixed
+---------------------------------------+
Total: ~5-6k tokens << 128k window
```

Key insight: **instead of stuffing all prior text into the context, we extract key information through the memory system**. This mirrors how human authors write -- they don't re-read the entire book before writing each paragraph.

### 5. Orchestrator vs. Decentralized

We chose the **Orchestrator pattern** (central coordinator) over fully decentralized agent interaction:

| Aspect | Orchestrator | Decentralized |
|--------|-------------|---------------|
| Debuggability | Clear, traceable flow | Hard to trace |
| Reliability | Explicit failure points | Cascading failures |
| Flexibility | Relatively fixed flow | Highly flexible |
| Best for | Pipeline tasks | Open-ended dialogue |

Novel writing is a pipeline task -- Orchestrator is the right fit.

## Q&A

### Q: Why multi-agent instead of a single LLM?

Three reasons:
1. **Separation of concerns**: Each agent has a dedicated system prompt, deeply optimized for its role. A single prompt trying to do everything produces worse results.
2. **Quality assurance**: Separating Writer and Editor implements the "generate-critique" split. Research shows (Du et al., 2023) that an independent critic is more effective than self-evaluation.
3. **Maintainability**: You can tune a single agent's prompt and parameters without affecting others.

### Q: How does the memory system differ from RAG?

Our memory system is essentially a **lightweight, domain-specialized RAG**:
- **Similar**: Both retrieve external information and inject it into the LLM context
- **Different**:
  - We use structured tags (chapter number, character name, importance score) instead of vector embeddings
  - We have three tiered layers (working/episodic/semantic), while typical RAG is flat
  - We have active compression and migration (working -> episodic -> semantic)

For novel writing, tag-based retrieval is more reliable than vector similarity -- we know exactly that we need events from chapter 5, not "the most semantically similar memory".

### Q: How do you ensure character consistency?

Three layers of defense:
1. **Initial state table**: The Character agent outputs structured initial states (JSON), stored in semantic memory
2. **Memory tracking**: After each chapter, MemoryManager extracts character state changes and updates semantic memory
3. **Consistency checker**: ConsistencyChecker compares the current chapter against character states in memory, detecting contradictions

### Q: How does this compare to MetaGPT / ChatDev / CrewAI?

Those are **general-purpose multi-agent frameworks**. NovelForge is a **domain-specialized system**:
- MetaGPT focuses on software development roles (PM / Architect / Engineer)
- ChatDev focuses on dialogue-driven code generation
- CrewAI provides a generic agent orchestration API

NovelForge is deeply optimized for long-form fiction:
- Tiered memory designed for ultra-long text
- Character and plot consistency tracking
- Chapter-level quality evaluation
- Literary quality dimensions in the review process

### Q: What are the bottlenecks?

**Latency**: Each chapter requires 3-5 LLM calls (writing + review + revision + memory compression). A 50-chapter novel = 150-250 API calls. Mitigation: parallel generation for independent chapters, reduced review rounds.

**Quality ceiling**: Emotional nuance is bounded by the base model. Dialogue personalization needs finer character system prompts. Long-range foreshadowing still depends on outline quality.

## Model Configuration

Default model: `qwen3.5-flash` on Alibaba Cloud DashScope (128K context window).

The LLM client uses the OpenAI-compatible protocol, making it easy to switch models:

```python
LLMConfig(
    model="qwen3.5-flash",         # or any other model
    base_url="https://...",        # API endpoint
    api_key="sk-...",
    max_tokens=16384,
    context_window=131072,         # 128k
    enable_thinking=True,          # thinking mode (if supported)
)
```

## References

- Park, J.S. et al. (2023). [Generative Agents: Interactive Simulacra of Human Behavior](https://arxiv.org/abs/2304.03442)
- Du, Y. et al. (2023). [Improving Factuality and Reasoning through Multiagent Debate](https://arxiv.org/abs/2305.14325)
- Shinn, N. et al. (2023). [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
- Packer, C. et al. (2023). [MemGPT: Towards LLMs as Operating Systems](https://arxiv.org/abs/2310.08560)
- Hong, S. et al. (2023). [MetaGPT: Meta Programming for Multi-Agent Collaborative Framework](https://arxiv.org/abs/2308.00352)
- Qian, C. et al. (2023). [ChatDev: Communicative Agents for Software Development](https://arxiv.org/abs/2307.07924)

## License

MIT
