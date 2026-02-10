import json
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ProjectSpec:
    title: str = ""
    idea: str = ""
    chapters: int = 5
    chapter_words: int = 2000
    volumes: int = 1
    batch_size: int = 5

    @property
    def target_words(self) -> int:
        return self.chapters * self.chapter_words

    def to_prompt(self) -> str:
        return (
            "【Production Parameters】\n"
            f"- Title: {self.title}\n"
            f"- Target Word Count: approx. {self.target_words:,} words\n"
            f"- Total Chapters: {self.chapters}\n"
            f"- Volumes/Phases: {self.volumes}\n"
            f"- Words per Chapter: {self.chapter_words}\n"
        )


DEFAULT_MODELS: Dict[str, str] = {
    "intent": "",
    "architect": "",
    "profiler": "",
    "weaver": "",
    "slicer": "",
    "writer": "",
    "checker": "",
    "memory": "",
}


class StateStore:
    def __init__(self):
        self.project_slug = "demo_project"
        self.spec = ProjectSpec()
        self.models = DEFAULT_MODELS.copy()
        self.chat_log: List[Dict[str, Any]] = []
        self.threads: Dict[str, List[Dict[str, str]]] = {}
        self.chapter_meta: Dict[str, Dict[str, Any]] = {}
        self.flow_stage: str = "init"
        self.created_at: float = 0.0
        self.updated_at: float = 0.0
        # Don't auto-load here to avoid side effects during listing
        # self.load(self.project_slug) 

    @property
    def state_path(self) -> Path:
        return self.get_project_dir() / "state.json"

    def list_projects(self) -> List[Dict[str, Any]]:
        projects = []
        if OUTPUT_DIR.exists():
            for p in OUTPUT_DIR.iterdir():
                if p.is_dir() and (p / "state.json").exists():
                    # Peak into state.json for metadata
                    try:
                        with open(p / "state.json", "r", encoding="utf-8") as f:
                            data = json.load(f)
                            spec = data.get("spec", {})
                            projects.append({
                                "slug": p.name,
                                "title": spec.get("title", "Untitled"),
                                "updated_at": data.get("updated_at", p.stat().st_mtime),
                                "created_at": data.get("created_at", 0),
                            })
                    except Exception:
                        continue
        # Sort by updated_at desc
        return sorted(projects, key=lambda x: x["updated_at"], reverse=True)

    def create_project(self, title: str = "") -> str:
        # Generate UUID as slug
        new_slug = uuid.uuid4().hex
        
        # Default title if empty
        if not title:
            title = f"Untitled Project {int(time.time())}"
            
        self.project_slug = new_slug
        self.spec = ProjectSpec(title=title)
        self.models = DEFAULT_MODELS.copy()
        self.chat_log = []
        self.threads = {}
        self.chapter_meta = {}
        self.flow_stage = "init"
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.save()
        return new_slug

    def load_project(self, slug: str) -> None:
        self.load(slug)

    def load(self, slug: Optional[str] = None) -> None:
        if slug:
            self.project_slug = slug
        
        if not self.state_path.exists():
            # Only auto-save if we have a valid slug, but uuid implies existence usually.
            # Fallback for old default "demo_project"
            if self.project_slug == "demo_project":
                 self.save()
            return

        data = self._read_json(self.state_path, {})
        spec_data = data.get("spec", {})
        self.spec = ProjectSpec(**{**asdict(ProjectSpec()), **spec_data})
        self.models.update(data.get("models", {}))
        self.project_slug = data.get("project_slug", self.project_slug)
        self.chat_log = data.get("chat_log", [])
        self.threads = data.get("threads", {})
        self.chapter_meta = data.get("chapter_meta", {})
        self.flow_stage = data.get("flow_stage", self.flow_stage)
        self.created_at = data.get("created_at", 0)
        self.updated_at = data.get("updated_at", 0)

    def save(self) -> None:
        self.updated_at = time.time()
        payload = {
            "spec": asdict(self.spec),
            "models": self.models,
            "project_slug": self.project_slug,
            "chat_log": self.chat_log,
            "threads": self.threads,
            "chapter_meta": self.chapter_meta,
            "flow_stage": self.flow_stage,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        self._write_json(self.state_path, payload)

    def update_spec(self, data: Dict[str, Any]) -> None:
        # Note: changing title now might imply changing slug, but robust renaming is complex.
        # For now, we update the spec but keep the slug stable unless we implement a migration.
        for key, value in data.items():
            if hasattr(self.spec, key):
                setattr(self.spec, key, value)
        self.save()

    def update_models(self, data: Dict[str, str]) -> None:
        for key, value in data.items():
            if key in self.models:
                self.models[key] = value
        self.save()

    def add_chat(self, entry: Dict[str, Any]) -> None:
        self.chat_log.append(entry)
        self.save()

    def add_thread_message(self, agent_id: str, role: str, content: str) -> None:
        self.threads.setdefault(agent_id, []).append({"role": role, "content": content})
        self.save()

    def reset_threads(self, agent_id: str) -> None:
        self.threads[agent_id] = []
        self.save()

    def set_chapter_meta(self, chapter_id: str, meta: Dict[str, Any]) -> None:
        self.chapter_meta[chapter_id] = meta
        self.save()

    def set_flow_stage(self, stage: str) -> None:
        self.flow_stage = stage
        self.save()

    def get_project_dir(self) -> Path:
        project_dir = OUTPUT_DIR / self.project_slug
        (project_dir / "chapters").mkdir(parents=True, exist_ok=True)
        (project_dir / "memory").mkdir(parents=True, exist_ok=True)
        return project_dir

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_json(self, path: Path, data: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def slugify(title: str) -> str:
    # Deprecated fallback
    safe = "".join(ch for ch in title if ch.isalnum() or ch in ("-", "_", " ")).strip()
    return safe.replace(" ", "_") or "demo_project"
