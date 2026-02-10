import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents import agent_map
from llm_manager import LLMService
from storage import ProjectSpec, StateStore


BASE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = BASE_DIR / "prompts"


def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def parse_jsonl(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return items


def write_jsonl(path: Path, items: List[Dict[str, Any]], mode: str = "w") -> None:
    with open(path, mode, encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False))
            f.write("\n")


class MemoryStore:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.memory_dir = project_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "short": self.memory_dir / "short.txt",
            "mid": self.memory_dir / "mid.txt",
            "long": self.memory_dir / "long.txt",
        }

    def get(self, name: str) -> str:
        path = self.paths.get(name)
        if not path or not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def set(self, name: str, content: str) -> None:
        path = self.paths.get(name)
        if not path:
            return
        path.write_text(content, encoding="utf-8")


class NovelPipeline:
    def __init__(self, state: StateStore, llm: LLMService):
        self.state = state
        self.llm = llm
        self.agents = agent_map()

    def run_architect(self, extra_instruction: str = "") -> str:
        spec = self.state.spec
        cached = self._read_project_file("series_bible.txt")
        if cached:
            return cached
        prompt = load_prompt(self.agents["architect"].prompt_file)
        user_prompt = (
            f"{spec.to_prompt()}\n"
            f"书名：{spec.title}\n"
            f"用户灵感：{spec.idea}\n\n"
            "请生成可落地的 Series Bible。"
        )
        if extra_instruction:
            user_prompt += f"\n\n【用户补充】\n{extra_instruction}"
        content = self._call_agent("architect", prompt, user_prompt)
        self._write_project_file("series_bible.txt", content)
        return content

    def run_profiler(self, extra_instruction: str = "") -> str:
        spec = self.state.spec
        cached = self._read_project_file("characters.txt")
        if cached:
            return cached
        bible = self._read_project_file("series_bible.txt")
        prompt = load_prompt(self.agents["profiler"].prompt_file)
        user_prompt = (
            f"{spec.to_prompt()}\n"
            f"【Series Bible】\n{bible}\n\n"
            "请生成角色系统。"
        )
        if extra_instruction:
            user_prompt += f"\n\n【用户补充】\n{extra_instruction}"
        content = self._call_agent("profiler", prompt, user_prompt)
        self._write_project_file("characters.txt", content)
        return content

    def run_weaver(self, extra_instruction: str = "") -> str:
        spec = self.state.spec
        cached = self._read_project_file("outline.jsonl")
        if cached:
            return cached
        bible = self._read_project_file("series_bible.txt")
        chars = self._read_project_file("characters.txt")
        prompt = load_prompt(self.agents["weaver"].prompt_file)
        user_prompt = (
            f"{spec.to_prompt()}\n"
            f"【Series Bible】\n{bible}\n\n"
            f"【角色档案】\n{chars}\n\n"
            f"请输出 CH1-CH{spec.chapters} 的章节目录。"
        )
        if extra_instruction:
            user_prompt += f"\n\n【用户补充】\n{extra_instruction}"
        content = self._call_agent("weaver", prompt, user_prompt)
        self._write_project_file("outline.jsonl", content)
        return content

    def run_slicer(self, start_ch: int, end_ch: int, extra_instruction: str = "") -> List[Dict[str, Any]]:
        spec = self.state.spec
        existing = self._get_existing_slices(start_ch, end_ch)
        if len(existing) == (end_ch - start_ch + 1):
            return existing
        bible = self._read_project_file("series_bible.txt")
        chars = self._read_project_file("characters.txt")
        outline = self._read_project_file("outline.jsonl")
        memory = self._get_memory_store()
        prompt = load_prompt(self.agents["slicer"].prompt_file)
        user_prompt = (
            f"{spec.to_prompt()}\n"
            f"本批次范围：CH{start_ch}-CH{end_ch}\n\n"
            f"【Series Bible】\n{self._truncate(bible, 4000)}\n\n"
            f"【角色档案】\n{self._truncate(chars, 3000)}\n\n"
            f"【章节目录】\n{self._truncate(outline, 4000)}\n\n"
            f"【短期记忆】\n{self._truncate(memory.get('short'), 1500)}\n"
        )
        if extra_instruction:
            user_prompt += f"\n【用户补充】\n{extra_instruction}"
        content = self._call_agent("slicer", prompt, user_prompt)
        slices = parse_jsonl(content)
        existing_map = {item.get("chapter"): item for item in existing}
        new_items = [item for item in slices if item.get("chapter") not in existing_map]
        self._append_jsonl("slices.jsonl", new_items)
        merged = {**existing_map, **{item.get("chapter"): item for item in new_items}}
        ordered = [merged.get(ch) for ch in range(start_ch, end_ch + 1) if merged.get(ch)]
        return ordered

    def run_writer(self, chapter_num: int, extra_instruction: str = "") -> str:
        spec = self.state.spec
        cached = self._read_existing_chapter(chapter_num)
        if cached:
            return cached
        slice_obj = self._find_slice(chapter_num)
        if not slice_obj:
            self.run_slicer(chapter_num, chapter_num)
            slice_obj = self._find_slice(chapter_num)
        if not slice_obj:
            raise ValueError(f"Slice not found for CH{chapter_num}")

        memory = self._get_memory_store()
        prompt = load_prompt(self.agents["writer"].prompt_file)
        prev_tail = self._get_prev_tail(chapter_num)
        user_prompt = (
            f"{spec.to_prompt()}\n"
            f"【章节切片】\n{json.dumps(slice_obj, ensure_ascii=False, indent=2)}\n\n"
            f"【短期记忆】\n{memory.get('short')}\n\n"
            f"【中期记忆】\n{memory.get('mid')}\n\n"
            f"【长期记忆】\n{memory.get('long')}\n\n"
            f"【上一章末尾】\n{prev_tail}\n"
        )
        if extra_instruction:
            user_prompt += f"\n【用户补充】\n{extra_instruction}"
        content = self._call_agent("writer", prompt, user_prompt, temperature=0.85)
        
        # Cleanup: Remove content after <章节结束>
        if "<章节结束>" in content:
            content = content.split("<章节结束>")[0].strip()

        filename = self._chapter_filename(chapter_num, slice_obj.get("title", "Untitled"))
        self._write_project_file(f"chapters/{filename}", content)
        self._update_chapter_meta(chapter_num, slice_obj.get("title", "Untitled"), "needs_review")
        self._update_memory(chapter_num, content)
        return content

    def run_checker(self, check_type: str, requirements: str, content: str) -> Dict[str, Any]:
        prompt = load_prompt(self.agents["checker"].prompt_file)
        user_prompt = (
            f"【检查类型】{check_type}\n"
            f"【要求】\n{requirements}\n\n"
            f"【内容】\n{content}\n"
        )
        raw = self._call_agent("checker", prompt, user_prompt, temperature=0.1)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "passed": False,
                "score": 40,
                "issues": ["检查输出不是合法 JSON"],
                "missing": [],
                "suggestion": "请重新输出 JSON。",
            }

    def _call_agent(self, role: str, system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
        model_override = self.state.models.get(role) or None
        return self.llm.call_text(role, system_prompt, user_prompt, temperature=temperature, model_id=model_override)

    def _read_project_file(self, relative: str) -> str:
        path = self.state.get_project_dir() / relative
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _write_project_file(self, relative: str, content: str) -> None:
        path = self.state.get_project_dir() / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _append_jsonl(self, relative: str, items: List[Dict[str, Any]]) -> None:
        if not items:
            return
        path = self.state.get_project_dir() / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_jsonl(path, items, mode="a")

    def _find_slice(self, chapter_num: int) -> Optional[Dict[str, Any]]:
        slices_path = self.state.get_project_dir() / "slices.jsonl"
        if not slices_path.exists():
            return None
        for item in parse_jsonl(slices_path.read_text(encoding="utf-8")):
            if item.get("chapter") == chapter_num:
                return item
        return None

    def _chapter_filename(self, chapter_num: int, title: str) -> str:
        safe_title = "".join(ch for ch in title if ch.isalnum() or ch in ("-", "_", " ")).strip()
        safe_title = safe_title or "chapter"
        return f"CH{chapter_num:04d}_{safe_title}.txt"

    def _get_prev_tail(self, chapter_num: int) -> str:
        if chapter_num <= 1:
            return "（无前文章节，这是第一章）"
        prev_num = chapter_num - 1
        chapters_dir = self.state.get_project_dir() / "chapters"
        for file in chapters_dir.glob(f"CH{prev_num:04d}_*.txt"):
            return file.read_text(encoding="utf-8")[-800:]
        return ""

    def _read_existing_chapter(self, chapter_num: int) -> str:
        chapters_dir = self.state.get_project_dir() / "chapters"
        for file in chapters_dir.glob(f"CH{chapter_num:04d}_*.txt"):
            return file.read_text(encoding="utf-8")
        return ""

    def _get_existing_slices(self, start_ch: int, end_ch: int) -> List[Dict[str, Any]]:
        slices_path = self.state.get_project_dir() / "slices.jsonl"
        if not slices_path.exists():
            return []
        items = parse_jsonl(slices_path.read_text(encoding="utf-8"))
        return [item for item in items if start_ch <= item.get("chapter", 0) <= end_ch]

    def _update_memory(self, chapter_num: int, content: str) -> None:
        memory = self._get_memory_store()
        prompt = load_prompt(self.agents["memory"].prompt_file)
        short_prompt = f"【最新章节内容】\n{self._truncate(content, 6000)}\n\n【现有记忆】\n{memory.get('short')}\n"
        short_summary = self._call_agent("memory", prompt, short_prompt, temperature=0.3)
        memory.set("short", short_summary)

        if chapter_num % 3 == 0:
            mid_prompt = f"【最新章节内容】\n{self._truncate(content, 6000)}\n\n【现有记忆】\n{memory.get('mid')}\n"
            mid_summary = self._call_agent("memory", prompt, mid_prompt, temperature=0.3)
            memory.set("mid", mid_summary)

        if chapter_num % 8 == 0:
            long_prompt = f"【最新章节内容】\n{self._truncate(content, 6000)}\n\n【现有记忆】\n{memory.get('long')}\n"
            long_summary = self._call_agent("memory", prompt, long_prompt, temperature=0.3)
            memory.set("long", long_summary)

    def _get_memory_store(self) -> MemoryStore:
        return MemoryStore(self.state.get_project_dir())

    def _update_chapter_meta(self, chapter_num: int, title: str, status: str) -> None:
        chapter_id = f"CH{chapter_num:04d}"
        self.state.set_chapter_meta(
            chapter_id,
            {"chapter": chapter_num, "title": title, "status": status},
        )

    def _truncate(self, text: str, max_chars: int) -> str:
        return text if len(text) <= max_chars else text[:max_chars]
