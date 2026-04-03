"""Orchestrator — the central coordinator of the multi-agent pipeline.

This is the "brain" of NovelForge, implementing:

1. **Pipeline orchestration**: Runs agents in the correct sequence
   (WorldBuilder → Character → Outliner → Writer → Editor)

2. **Writer-Editor debate loop**: After the Writer generates a chapter,
   the Editor reviews it. If score < threshold, the Writer revises.
   This loop runs up to max_review_rounds times.

3. **Memory management**: After each chapter, compresses content into
   the hierarchical memory system.

4. **Fault tolerance**: Catches agent failures and allows retry/skip.

Architecture pattern: Orchestrator (central coordinator)
  - Used by AutoGen, CrewAI, and Claude Code
  - Simpler than fully decentralized patterns
  - Easy to debug and reason about
  - Natural fit for pipeline-style workflows
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

from novelforge.core.config import Config
from novelforge.core.llm import LLMClient
from novelforge.core.message import Message, MessageBus, MessageType
from novelforge.memory import MemoryManager
from novelforge.agents.worldbuilder import WorldBuilderAgent
from novelforge.agents.character import CharacterAgent
from novelforge.agents.outliner import OutlinerAgent
from novelforge.agents.writer import WriterAgent
from novelforge.agents.editor import EditorAgent

logger = logging.getLogger(__name__)

# Type for progress callbacks used by the TUI
ProgressCallback = Callable[[str, str, float], None]


class Orchestrator:
    """Central coordinator for the novel writing pipeline.

    Usage:
        config = Config(...)
        orch = Orchestrator(config)
        orch.run()              # Run the full pipeline
        orch.run_chapter(5)     # Generate a single chapter
    """

    def __init__(self, config: Config, on_progress: Optional[ProgressCallback] = None):
        self.config = config
        self.llm = LLMClient(config.llm)
        self.bus = MessageBus()
        self.on_progress = on_progress or (lambda *_: None)

        # Initialize memory
        self.memory = MemoryManager(config.project_dir, self.llm)

        # Initialize agents — each gets the shared LLM client and message bus
        self.worldbuilder = WorldBuilderAgent(self.llm, self.bus, config)
        self.character = CharacterAgent(self.llm, self.bus, config)
        self.outliner = OutlinerAgent(self.llm, self.bus, config)
        self.writer = WriterAgent(self.llm, self.bus, config)
        self.editor = EditorAgent(self.llm, self.bus, config)

        # Pipeline state
        self._world_bible = ""
        self._characters = ""
        self._outline = ""
        self._chapters: dict[int, str] = {}
        self._reviews: dict[int, dict] = {}

        # Load any existing progress
        self._load_state()

    # -- Full Pipeline ---------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the complete novel generation pipeline.

        Returns a summary dict with generation stats.
        """
        start_time = time.time()
        spec = self.config.novel
        total_steps = 3 + spec.chapters  # worldbuild + character + outline + N chapters

        # Phase 1: World Building
        if not self._world_bible:
            self._progress("worldbuilder", "生成 Series Bible...", 1 / total_steps)
            self._world_bible = self.worldbuilder.execute(idea=spec.idea)
            self._save_artifact("series_bible.txt", self._world_bible)
            self._extract_spec_from_bible(self._world_bible)

        # Phase 2: Character Design
        if not self._characters:
            self._progress("character", "设计角色系统...", 2 / total_steps)
            self._characters = self.character.execute(world_bible=self._world_bible)
            self._save_artifact("characters.txt", self._characters)
            self._init_character_states(self._characters)

        # Phase 3: Outline
        if not self._outline:
            self._progress("outliner", "编排章节大纲...", 3 / total_steps)
            self._outline = self.outliner.execute(
                world_bible=self._world_bible,
                characters=self._characters,
            )
            self._save_artifact("outline.jsonl", self._outline)

        # Phase 4: Chapter Writing (with Editor review loop)
        for ch_num in range(1, spec.chapters + 1):
            if ch_num in self._chapters:
                continue
            progress = (3 + ch_num) / total_steps
            self._progress("writer", f"撰写第{ch_num}章...", progress)
            chapter_text = self._write_chapter_with_review(ch_num)
            self._chapters[ch_num] = chapter_text

        elapsed = time.time() - start_time
        return {
            "chapters_written": len(self._chapters),
            "total_words": sum(len(ch) for ch in self._chapters.values()),
            "elapsed_seconds": elapsed,
            "total_tokens": self.llm.total_input_tokens + self.llm.total_output_tokens,
        }

    # -- Single Chapter --------------------------------------------------------

    def run_chapter(self, chapter_num: int) -> str:
        """Generate a single chapter (prerequisites must exist)."""
        if not self._outline:
            raise RuntimeError("大纲尚未生成，请先运行完整流程或生成大纲。")
        return self._write_chapter_with_review(chapter_num)

    # -- Writer-Editor Debate Loop ---------------------------------------------

    def _write_chapter_with_review(self, chapter_num: int) -> str:
        """Write a chapter, then run Editor review loop.

        Implements the debate pattern:
        1. Writer generates draft
        2. Editor reviews draft → score + feedback
        3. If score < 70, Writer revises (up to max_review_rounds)
        4. Final version is saved and memory is updated

        This is the core multi-agent interaction in the system.
        """
        chapter_slice = self.outliner.get_chapter_slice(self._outline, chapter_num)
        if not chapter_slice:
            raise ValueError(f"大纲中找不到第{chapter_num}章")

        memory_ctx = self.memory.get_context_for_writing(chapter_num)
        prev_tail = self._get_prev_tail(chapter_num)

        # --- Step 1: Writer generates draft ---
        self._progress("writer", f"第{chapter_num}章 - 初稿写作中...", 0)
        draft = self.writer.execute(
            chapter_slice=chapter_slice,
            memory_context=memory_ctx,
            prev_tail=prev_tail,
        )

        # --- Step 2-3: Editor review loop (debate pattern) ---
        if self.config.pipeline.enable_self_reflection:
            max_rounds = self.config.pipeline.max_review_rounds
            for round_num in range(max_rounds):
                self._progress("editor", f"第{chapter_num}章 - 第{round_num + 1}轮审查...", 0)
                review = self.editor.execute(
                    draft=draft,
                    chapter_slice=chapter_slice,
                    memory_context=memory_ctx,
                    characters=self._characters,
                )
                self._reviews[chapter_num] = review

                score = review.get("total_score", 100)
                verdict = review.get("verdict", "pass")

                if verdict == "pass" or score >= 70:
                    self._progress("editor", f"第{chapter_num}章 - 审查通过 ({score}分)", 0)
                    break

                # Writer revises based on Editor's feedback
                self._progress("writer", f"第{chapter_num}章 - 第{round_num + 1}轮修订...", 0)
                revision_prompt = self.editor.generate_revision_prompt(draft, review)
                draft = self.writer.execute(
                    chapter_slice=chapter_slice,
                    memory_context=memory_ctx,
                    prev_tail=prev_tail,
                    extra=revision_prompt,
                )

        # --- Step 4: Save and update memory ---
        title = chapter_slice.get("title", f"第{chapter_num}章")
        filename = f"CH{chapter_num:04d}_{title}.txt"
        self._save_artifact(f"chapters/{filename}", draft)

        # Compress chapter into memory for future chapters
        self._progress("memory", f"第{chapter_num}章 - 更新记忆...", 0)
        self.memory.compress_chapter(chapter_num, draft)

        self._save_state()
        return draft

    # -- State Persistence -----------------------------------------------------

    def _save_artifact(self, relative: str, content: str) -> None:
        """Save a generated artifact to the project directory."""
        path = self.config.project_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _load_artifact(self, relative: str) -> str:
        path = self.config.project_dir / relative
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _save_state(self) -> None:
        """Save orchestrator state for resumability."""
        state = {
            "chapters_done": list(self._chapters.keys()),
            "reviews": {str(k): v for k, v in self._reviews.items()},
        }
        path = self.config.project_dir / "pipeline_state.json"
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

    def _load_state(self) -> None:
        """Load existing artifacts and pipeline state."""
        self._world_bible = self._load_artifact("series_bible.txt")
        self._characters = self._load_artifact("characters.txt")
        self._outline = self._load_artifact("outline.jsonl")

        # Load existing chapters
        chapters_dir = self.config.project_dir / "chapters"
        if chapters_dir.exists():
            for f in chapters_dir.glob("CH*.txt"):
                try:
                    num = int(f.stem.split("_")[0].replace("CH", ""))
                    self._chapters[num] = f.read_text(encoding="utf-8")
                except (ValueError, IndexError):
                    continue

        # Load pipeline state
        state_path = self.config.project_dir / "pipeline_state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                for k, v in state.get("reviews", {}).items():
                    self._reviews[int(k)] = v
            except (json.JSONDecodeError, ValueError):
                pass

    def _get_prev_tail(self, chapter_num: int, chars: int = 800) -> str:
        """Get the tail of the previous chapter for continuity."""
        if chapter_num <= 1:
            return "（第一章，无前文）"
        prev = self._chapters.get(chapter_num - 1, "")
        if not prev:
            return ""
        return prev[-chars:]

    def _extract_spec_from_bible(self, bible: str) -> None:
        """Try to extract title from the generated Series Bible."""
        import re
        title_match = re.search(r"【书名】\s*(.*)", bible)
        if title_match:
            raw = title_match.group(1).strip()
            clean = re.sub(r"[*《》#\[\]]", "", raw).strip()
            if clean and not self.config.novel.title:
                self.config.novel.title = clean

    def _init_character_states(self, characters_text: str) -> None:
        """Extract initial character states and store in semantic memory."""
        # Try to find JSON block in character profiles
        import re
        json_match = re.search(r'\{[\s\S]*"characters"[\s\S]*\}', characters_text)
        if not json_match:
            return
        try:
            data = json.loads(json_match.group())
            for char in data.get("characters", []):
                name = char.get("name", "unknown")
                self.memory.add_semantic(
                    key=f"char_init_{name}",
                    content=f"{name} 初始状态: 位于{char.get('location', '未知')}，"
                            f"情绪{char.get('mood', '平静')}",
                    importance=8,
                    tags=["character", "state", name],
                )
        except (json.JSONDecodeError, TypeError):
            pass

    def _progress(self, agent: str, message: str, fraction: float) -> None:
        """Report progress to the callback (used by TUI)."""
        self.on_progress(agent, message, fraction)

    # -- Public accessors for TUI/API ------------------------------------------

    @property
    def world_bible(self) -> str:
        return self._world_bible

    @property
    def characters(self) -> str:
        return self._characters

    @property
    def outline(self) -> str:
        return self._outline

    @property
    def chapters(self) -> dict[int, str]:
        return dict(self._chapters)

    @property
    def reviews(self) -> dict[int, dict]:
        return dict(self._reviews)

    def get_stats(self) -> dict[str, Any]:
        """Get current pipeline statistics."""
        return {
            "has_bible": bool(self._world_bible),
            "has_characters": bool(self._characters),
            "has_outline": bool(self._outline),
            "chapters_done": sorted(self._chapters.keys()),
            "chapters_total": self.config.novel.chapters,
            "total_words": sum(len(ch) for ch in self._chapters.values()),
            "total_tokens": self.llm.total_input_tokens + self.llm.total_output_tokens,
        }
