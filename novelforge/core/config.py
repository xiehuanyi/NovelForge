"""Global configuration for NovelForge."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    model: str = "qwen3.5-flash"
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    max_tokens: int = 16384
    context_window: int = 131072  # 128k
    enable_thinking: bool = True


@dataclass
class NovelSpec:
    """Novel specification — what we're writing."""
    title: str = ""
    idea: str = ""
    genre: str = ""
    style: str = ""
    chapters: int = 10
    chapter_words: int = 3000
    volumes: int = 1

    @property
    def total_words(self) -> int:
        return self.chapters * self.chapter_words

    def to_context(self) -> str:
        """Format spec as context string for prompts."""
        lines = [
            "【小说规格】",
            f"  书名: {self.title or '待定'}",
            f"  类型: {self.genre or '待定'}",
            f"  风格: {self.style or '待定'}",
            f"  总章数: {self.chapters}",
            f"  每章字数: ~{self.chapter_words}",
            f"  总字数目标: ~{self.total_words:,}",
            f"  分卷数: {self.volumes}",
        ]
        if self.idea:
            lines.append(f"  核心创意: {self.idea}")
        return "\n".join(lines)


@dataclass
class PipelineConfig:
    """Pipeline behavior configuration."""
    max_review_rounds: int = 2          # Editor review iterations
    batch_size: int = 5                  # Chapters per batch for long novels
    enable_consistency_check: bool = True
    enable_self_reflection: bool = True
    parallel_writing: bool = False       # Parallel chapter generation
    memory_compression_interval: int = 3 # Compress memory every N chapters


@dataclass
class Config:
    """Top-level configuration."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    novel: NovelSpec = field(default_factory=NovelSpec)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    output_dir: str = "output"
    project_name: str = ""

    @property
    def project_dir(self) -> Path:
        name = self.project_name or "default"
        p = Path(self.output_dir) / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, path: Optional[Path] = None) -> None:
        path = path or self.project_dir / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = json.loads(path.read_text())
        return cls(
            llm=LLMConfig(**data.get("llm", {})),
            novel=NovelSpec(**data.get("novel", {})),
            pipeline=PipelineConfig(**data.get("pipeline", {})),
            output_dir=data.get("output_dir", "output"),
            project_name=data.get("project_name", ""),
        )
