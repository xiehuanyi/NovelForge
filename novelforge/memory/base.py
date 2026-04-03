"""Base memory storage with file-based persistence.

Design choice: file-based storage (like Claude Code's MEMORY.md approach)
rather than a vector database. This keeps dependencies minimal and makes
the memory system transparent and debuggable — you can read the memory
files directly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class MemoryEntry:
    """A single memory record.

    Fields:
        key: unique identifier (e.g., "ch3_event_fight", "char_state_alice")
        category: working / episodic / semantic
        content: the memory text
        tags: searchable tags for retrieval
        importance: 1-10 score for memory prioritization
        chapter: associated chapter number (if applicable)
        created_at: timestamp
    """
    key: str
    category: str
    content: str
    tags: list[str] = field(default_factory=list)
    importance: int = 5
    chapter: Optional[int] = None
    created_at: float = field(default_factory=time.time)


class MemoryStore:
    """File-based memory store with JSON persistence.

    Each memory layer is a directory containing individual JSON files.
    An index.json file maps keys to filenames for fast lookup.

    Directory structure:
        memory/
        ├── working/          # Current context
        │   ├── index.json
        │   └── *.json
        ├── episodic/         # Event records
        │   ├── index.json
        │   └── *.json
        └── semantic/         # Facts and states
            ├── index.json
            └── *.json
    """

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._index: dict[str, MemoryEntry] = {}
        self._load_index()

    def add(self, entry: MemoryEntry) -> None:
        """Add or update a memory entry."""
        self._index[entry.key] = entry
        self._save_entry(entry)
        self._save_index()

    def get(self, key: str) -> Optional[MemoryEntry]:
        """Get a specific memory by key."""
        return self._index.get(key)

    def search(
        self,
        tags: Optional[list[str]] = None,
        category: Optional[str] = None,
        chapter: Optional[int] = None,
        min_importance: int = 0,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Search memories by tags, category, chapter, or importance.

        Returns entries sorted by importance (descending), then recency.
        """
        results = list(self._index.values())

        if category:
            results = [m for m in results if m.category == category]
        if chapter is not None:
            results = [m for m in results if m.chapter == chapter]
        if min_importance > 0:
            results = [m for m in results if m.importance >= min_importance]
        if tags:
            tag_set = set(tags)
            results = [m for m in results if tag_set & set(m.tags)]

        results.sort(key=lambda m: (-m.importance, -m.created_at))
        return results[:limit]

    def get_all(self, category: Optional[str] = None) -> list[MemoryEntry]:
        """Get all memories, optionally filtered by category."""
        entries = list(self._index.values())
        if category:
            entries = [m for m in entries if m.category == category]
        return sorted(entries, key=lambda m: m.created_at)

    def remove(self, key: str) -> None:
        """Remove a memory entry."""
        if key in self._index:
            del self._index[key]
            entry_path = self.base_dir / f"{key}.json"
            if entry_path.exists():
                entry_path.unlink()
            self._save_index()

    def clear(self, category: Optional[str] = None) -> None:
        """Clear all memories or only a specific category."""
        keys_to_remove = [
            k for k, v in self._index.items()
            if category is None or v.category == category
        ]
        for key in keys_to_remove:
            self.remove(key)

    def to_context(self, category: Optional[str] = None, limit: int = 30) -> str:
        """Format memories as a context string for LLM prompts."""
        entries = self.search(category=category, limit=limit)
        if not entries:
            return "（无记录）"
        lines = []
        for e in entries:
            prefix = f"[CH{e.chapter}] " if e.chapter else ""
            lines.append(f"- {prefix}{e.content}")
        return "\n".join(lines)

    # -- Persistence -----------------------------------------------------------

    def _load_index(self) -> None:
        index_path = self.base_dir / "index.json"
        if not index_path.exists():
            return
        try:
            data = json.loads(index_path.read_text())
            for key, entry_data in data.items():
                self._index[key] = MemoryEntry(**entry_data)
        except (json.JSONDecodeError, TypeError):
            pass

    def _save_index(self) -> None:
        index_path = self.base_dir / "index.json"
        data = {k: asdict(v) for k, v in self._index.items()}
        index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _save_entry(self, entry: MemoryEntry) -> None:
        path = self.base_dir / f"{entry.key}.json"
        path.write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2))
