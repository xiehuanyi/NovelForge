"""Hierarchical memory system for long-form novel generation.

Three memory layers, inspired by cognitive science and Generative Agents (Park et al., 2023):

1. **Working Memory** — Current chapter context, recent events (like human short-term memory)
2. **Episodic Memory** — Chapter-level event sequences, stored as structured records
3. **Semantic Memory** — Extracted facts: character states, world rules, relationships

Plus a **MemoryManager** that handles compression and retrieval across all layers.
"""

from novelforge.memory.base import MemoryEntry, MemoryStore
from novelforge.memory.manager import MemoryManager

__all__ = ["MemoryEntry", "MemoryStore", "MemoryManager"]
