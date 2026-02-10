import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from agents import AGENTS, GUIDE_MESSAGE, agent_map
from llm_manager import LLMService
from pipeline import NovelPipeline
from storage import StateStore
STATIC_DIR = BASE_DIR / "static"
CONFIG_PATH = BASE_DIR / "models_config.json"

app = FastAPI()
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

state = StateStore()
llm = LLMService(str(CONFIG_PATH))
pipeline = NovelPipeline(state, llm)


class ChatRequest(BaseModel):
    message: str
    agent_id: Optional[str] = None


class SettingsRequest(BaseModel):
    title: Optional[str] = None
    idea: Optional[str] = None
    chapters: Optional[int] = None
    chapter_words: Optional[int] = None
    volumes: Optional[int] = None
    batch_size: Optional[int] = None
    models: Optional[Dict[str, str]] = None


class StepRequest(BaseModel):
    step: str
    start_ch: Optional[int] = None
    end_ch: Optional[int] = None
    chapter: Optional[int] = None


class ChapterStatusRequest(BaseModel):
    chapter_id: str
    status: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/agents")
def get_agents() -> List[Dict[str, Any]]:
    return [
        {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "description": agent.description,
            "color": agent.color,
            "hidden": agent.hidden,
        }
        for agent in AGENTS
    ]


@app.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    state.load() # Reload to sync with manual disk edits
    _sync_default_models()
    return {
        "spec": state.spec.__dict__,
        "models": state.models,
        "project_slug": state.project_slug,
        "total_tokens": _calculate_total_tokens()
    }

def _calculate_total_tokens() -> int:
    """Estimated token count from file sizes."""
    if not state.project_slug: 
        return 0
    total_bytes = 0
    project_dir = state.get_project_dir()
    for f in project_dir.rglob("*"):
        if f.is_file() and f.suffix in {".txt", ".json", ".jsonl"}:
            total_bytes += f.stat().st_size
    # Rough estimate: 1 token ~= 4 chars (English), but for Chinese/Mix implies chars. 
    # Let's just return char count / 2 or similiar, or just raw bytes/chars.
    # User asked for "Generated Tokens", effectively characters for CN.
    # Let's assume bytes ~ chars for UTF8 mostly (or just count bytes)
    return int(total_bytes / 3) # Very rough approximation for UTF-8 Chinese/English mix

class ChapterSaveRequest(BaseModel):
    chapter_id: str
    content: str
@app.post("/api/chapter/save")
def save_chapter(req: ChapterSaveRequest) -> Dict[str, str]:
    chapters_dir = state.get_project_dir() / "chapters"
    matches = list(chapters_dir.glob(f"{req.chapter_id}_*.txt"))
    if not matches:
        raise HTTPException(status_code=404, detail="Chapter not found")
    
    # Write content
    matches[0].write_text(req.content, encoding="utf-8")
    return {"status": "ok"}


@app.get("/api/models")
def get_models() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"models": []}
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"models": list(config.get("models", {}).keys())}


class ProjectActionRequest(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None


@app.get("/api/projects")
def list_projects() -> List[Dict[str, Any]]:
    return state.list_projects()


@app.post("/api/projects/new")
def create_project(req: ProjectActionRequest) -> Dict[str, str]:
    # Title is optional now, handled by storage
    slug = state.create_project(req.title or "")
    return {"status": "ok", "slug": slug}


@app.post("/api/projects/switch")
def switch_project(req: ProjectActionRequest) -> Dict[str, str]:
    if not req.slug:
        raise HTTPException(status_code=400, detail="Slug required")
    state.load_project(req.slug)
    # Re-sync default models if needed, though load() handles most.
    _sync_default_models()
    return {"status": "ok", "slug": state.project_slug}


@app.post("/api/settings")
def update_settings(req: SettingsRequest) -> Dict[str, Any]:
    spec_updates = req.dict(exclude_unset=True, exclude={"models"})
    if spec_updates:
        state.update_spec(spec_updates)
    if req.models:
        state.update_models(req.models)
    return {"status": "ok", "spec": state.spec.__dict__, "models": state.models}


@app.get("/api/chat")
def get_chat_log() -> List[Dict[str, Any]]:
    _ensure_intro_message()
    return state.chat_log


@app.post("/api/chat")
def post_chat(req: ChatRequest) -> Dict[str, Any]:
    agents = agent_map()
    agent_id, cleaned = _resolve_agent(req.message, req.agent_id)
    if agent_id not in agents:
        raise HTTPException(status_code=404, detail="Unknown agent")

    _ensure_intro_message()
    history = _format_history(agent_id)
    user_entry = _make_chat_entry("user", agent_id, cleaned)
    state.add_chat(user_entry)
    state.add_thread_message(agent_id, "user", cleaned)

    if agent_id == "guide" and cleaned.strip():
        response = _orchestrate_message(cleaned)
        reply = response["reply"]
        response_agent = response["agent_id"]
        
        # Collect extra data like 'setup_data' or 'trigger_auto_gen'
        extra_data = {k: v for k, v in response.items() if k not in ("reply", "agent_id", "dispatch_message")}
        
        dispatch_message = response.get("dispatch_message")
        if dispatch_message and response_agent != agent_id:
            agent_name = agents[response_agent].name
            dispatch_entry = _make_chat_entry(
                "assistant",
                "guide",
                f"已派发给 @{agent_name}：{dispatch_message}",
            )
            state.add_chat(dispatch_entry)
            state.add_thread_message(response_agent, "user", dispatch_message)
    elif agent_id == "guide":
        reply = GUIDE_MESSAGE
        response_agent = agent_id
        extra_data = {}
    else:
        reply = _run_agent_chat(agent_id, cleaned, history, explicit=True)
        response_agent = agent_id
        extra_data = {}

    assistant_entry = _make_chat_entry("assistant", response_agent, reply, **extra_data)
    state.add_chat(assistant_entry)
    state.add_thread_message(response_agent, "assistant", reply)
    return assistant_entry


# ... (skipping unchanged code) ...


def _make_chat_entry(role: str, agent_id: str, content: str, **kwargs) -> Dict[str, Any]:
    entry = {
        "id": f"{int(time.time() * 1000)}-{agent_id}-{role}",
        "role": role,
        "agent_id": agent_id,
        "content": content,
        "timestamp": time.time(),
    }
    entry.update(kwargs)
    return entry


@app.post("/api/step")
def run_step(req: StepRequest) -> Dict[str, Any]:
    step = req.step.lower()
    _sync_default_models()
    try:
        if step == "architect":
            content = pipeline.run_architect()
            state.set_flow_stage("architect")
        elif step == "profiler":
            content = pipeline.run_profiler()
            state.set_flow_stage("profiler")
        elif step == "weaver":
            content = pipeline.run_weaver()
            state.set_flow_stage("weaver")
        elif step == "slicer":
            if req.start_ch is None or req.end_ch is None:
                raise HTTPException(status_code=400, detail="start_ch/end_ch required")
            slices = pipeline.run_slicer(req.start_ch, req.end_ch)
            return {"status": "ok", "count": len(slices)}
        elif step == "writer":
            chapter = req.chapter or req.start_ch
            if not chapter:
                raise HTTPException(status_code=400, detail="chapter required")
            content = pipeline.run_writer(chapter)
            state.set_flow_stage("writer")
        else:
            raise HTTPException(status_code=400, detail="Unknown step")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "ok", "preview": content[:1000]}


@app.get("/api/preview/chapters")
def list_chapters() -> List[Dict[str, Any]]:
    chapters = _sync_chapter_meta()
    return sorted(chapters.values(), key=lambda x: x.get("chapter", 0))


@app.get("/api/preview/chapter/{chapter_id}")
def get_chapter(chapter_id: str) -> Dict[str, Any]:
    chapters_dir = state.get_project_dir() / "chapters"
    matches = list(chapters_dir.glob(f"{chapter_id}_*.txt"))
    if not matches:
        raise HTTPException(status_code=404, detail="Chapter not found")
    content = matches[0].read_text(encoding="utf-8")
    meta = state.chapter_meta.get(chapter_id, {})
    return {"chapter_id": chapter_id, "title": meta.get("title", ""), "content": content}


@app.post("/api/preview/status")
def update_chapter_status(req: ChapterStatusRequest) -> Dict[str, Any]:
    if req.chapter_id not in state.chapter_meta:
        raise HTTPException(status_code=404, detail="Chapter not found")
    meta = state.chapter_meta[req.chapter_id]
    meta["status"] = req.status
    state.set_chapter_meta(req.chapter_id, meta)
    return {"status": "ok"}
    return {"status": "ok"}


@app.post("/api/auto_generate")
def auto_generate_chapter() -> Dict[str, Any]:
    """Auto-generates the next missing step or chapter."""
    next_step = _get_next_pipeline_step()
    
    if not next_step:
        return {"status": "complete"}
    
    try:
        if next_step == "weaver":
            content = pipeline.run_weaver()
            return {
                "status": "generated",
                "chapter": "Outline", # Special handling in frontend?
                "content": content
            }
        elif next_step == "profiler":
            content = pipeline.run_profiler()
            return {
                "status": "generated",
                "chapter": "Characters",
                "content": content
            }
        elif next_step == "writer":
            next_ch = _next_missing_chapter()
            if not next_ch:
                 return {"status": "complete"}
            content = pipeline.run_writer(next_ch)
            return {
                "status": "generated",
                "chapter": next_ch,
                "content": content
            }
        # Fallback
        return {"status": "complete"}

    except Exception as e:
        return {
            "status": "error", 
            "message": str(e),
            "chapter": next_step
        }

def _load_prompt(filename: str) -> str:
    if not filename:
        return ""
    path = BASE_DIR / "prompts" / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _ensure_intro_message() -> None:
    if any(msg.get("agent_id") == "guide" for msg in state.chat_log):
        return
    entry = _make_chat_entry("assistant", "guide", GUIDE_MESSAGE)
    state.add_chat(entry)
    state.add_thread_message("guide", "assistant", GUIDE_MESSAGE)


def _format_history(agent_id: str, limit: int = 6) -> str:
    history = state.threads.get(agent_id, [])[-limit:]
    lines = []
    for msg in history:
        role = "用户" if msg["role"] == "user" else "助手"
        lines.append(f"{role}：{msg['content']}")
    return "\n".join(lines) if lines else "（无）"


def _build_agent_context(agent_id: str) -> str:
    spec = state.spec.to_prompt()
    stage = f"【当前阶段】{state.flow_stage}"
    bible = _read_project_file("series_bible.txt")
    chars = _read_project_file("characters.txt")
    outline = _read_project_file("outline.jsonl")
    latest = _latest_chapter_excerpt()

    context = [spec, stage]
    if agent_id == "architect" and bible:
        context.append("【当前 Series Bible】\n" + _truncate(bible, 6000))
    if bible:
        context.append("【Series Bible 摘要】\n" + _truncate(bible, 1500))
    if agent_id == "profiler" and chars:
        context.append("【当前角色档案】\n" + _truncate(chars, 6000))
    if chars:
        context.append("【角色档案 摘要】\n" + _truncate(chars, 1200))
    if agent_id == "weaver" and outline:
        context.append("【当前章节目录】\n" + _truncate(outline, 6000))
    if outline and agent_id in {"weaver", "writer", "checker"}:
        context.append("【章节目录 摘要】\n" + _truncate(outline, 1200))
    if latest and agent_id in {"writer", "checker"}:
        context.append("【最近章节摘录】\n" + latest)

    # Context injection for Writer
    if agent_id == "writer":
        target_ch = _next_missing_chapter() or _latest_chapter_number() or 1
        # Slice
        slice_obj = pipeline._find_slice(target_ch)
        if slice_obj:
            context.append(f"【当前章节切片 (CH{target_ch})】\n" + json.dumps(slice_obj, ensure_ascii=False, indent=2))
        else:
             # Try to start slicer if slice missing? Or just warn?
             pass 
        
        # Memory
        memory = pipeline._get_memory_store()
        if memory.get("short"):
             context.append(f"【短期记忆】\n{memory.get('short')}")
        if memory.get("mid"):
             context.append(f"【中期记忆】\n{memory.get('mid')}")
        if memory.get("long"):
             context.append(f"【长期记忆】\n{memory.get('long')}")
        
        # Prev Tail
        prev_tail = pipeline._get_prev_tail(target_ch)
        if prev_tail:
             context.append(f"【上一章末尾】\n{prev_tail}")

    return "\n\n".join(context)


def _read_project_file(relative: str) -> str:
    path = state.get_project_dir() / relative
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _latest_chapter_excerpt() -> str:
    chapters_dir = state.get_project_dir() / "chapters"
    chapters = list(chapters_dir.glob("CH*.txt"))
    if not chapters:
        return ""
    latest = sorted(chapters)[-1]
    return _truncate(latest.read_text(encoding="utf-8"), 1200)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars]


def _sync_default_models() -> None:
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults = config.get("default_role_models", {})
        role_map = {
            "memory": "memory_compressor",
        }
        updated = False
        for role in state.models:
            if state.models[role]:
                continue
            config_key = role_map.get(role, role)
            if config_key in defaults:
                state.models[role] = defaults[config_key]
                updated = True
        if updated:
            state.save()


def _sync_chapter_meta() -> Dict[str, Dict[str, Any]]:
    chapters_dir = state.get_project_dir() / "chapters"
    if not chapters_dir.exists():
        return state.chapter_meta
    for file in chapters_dir.glob("CH*.txt"):
        chapter_id = file.stem.split("_")[0]
        if chapter_id not in state.chapter_meta:
            title = "_".join(file.stem.split("_")[1:]) or "Untitled"
            number = int(chapter_id.replace("CH", ""))
            state.set_chapter_meta(
                chapter_id,
                {"chapter": number, "title": title, "status": "needs_review"},
            )
    return state.chapter_meta


def _resolve_agent(message: str, explicit_agent: Optional[str]) -> tuple[str, str]:
    if explicit_agent:
        return explicit_agent, message.strip()
    mention = _extract_mention(message)
    if mention:
        agent_id, cleaned = mention
        return agent_id, cleaned
    return "guide", message.strip()


def _extract_mention(message: str) -> Optional[tuple[str, str]]:
    candidates: List[tuple[int, str, str]] = []
    for agent in AGENTS:
        for token in (agent.name, agent.agent_id):
            marker = f"@{token}"
            idx = message.find(marker)
            if idx >= 0:
                candidates.append((idx, agent.agent_id, marker))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    _, agent_id, marker = candidates[0]
    cleaned = message.replace(marker, "", 1).strip()
    return agent_id, cleaned


def _orchestrate_message(message: str) -> Dict[str, str]:
    normalized = message.strip()
    intent = _call_intent(normalized)

    if _is_continue(normalized):
        return _handle_continue()

    chapter_num = _parse_chapter_number(normalized)
    range_info = _parse_chapter_range(normalized)
    keyword_target = _infer_agent_by_keywords(normalized)
    suggested = intent.get("target_agent") if isinstance(intent, dict) else None
    
    # Priority: Intent > Keywords (was reversed)
    target = suggested or keyword_target
    
    instruction = intent.get("instruction") if isinstance(intent, dict) else None
    instruction = instruction or normalized
    action = intent.get("action") if isinstance(intent, dict) else None

    # Enforce Prerequisites & Setup Flow
    has_bible = _read_project_file("series_bible.txt")
    
    # New Project Setup Flow
    if not has_bible and not normalized.startswith("@"):
        # Unless user is explicitly calling architect (compelled by the confirmation button), we try to help them setup
        setup_data = _extract_setup_intent(normalized)
        
        # Fallback: If extraction failed or returned empty, but user said something substantial, 
        # treat it as the idea and show form anyway.
        if not setup_data:
             if len(normalized) > 1: # Any input
                 setup_data = {
                     "title": None,
                     "idea": normalized,
                     "genre": None,
                     "style": None,
                     "chapters": 10,
                     "chapter_words": 2000
                 }
        
        if setup_data:
             return {
                 "agent_id": "guide", 
                 "reply": "收到创意！在开工前，我们先确认一下基础规格：",
                 "setup_data": setup_data
             }
        else:
             return {
                 "agent_id": "guide",
                 "reply": "请告诉我你想写什么类型的小说，或者给我一个核心灵感："
             }

    if target == "writer" or target == "slicer": # Treat slicer as writer (invisible step)
        if not has_bible:
             return _handle_step("architect", f"【系统强制路由】请先生成 Series Bible。用户原指令：{instruction}")
        if not _read_project_file("outline.jsonl"):
             return _handle_step("weaver", f"【系统强制路由】请先生成章节目录。用户原指令：{instruction}")
        # If user asked for slicer, redirect to writer which handles slicing internally
        target = "writer"



    if target == "writer":
        if not chapter_num:
            chapter_num = intent.get("chapter_number") if isinstance(intent, dict) else None
        if not chapter_num:
            chapter_num = _latest_chapter_number()
        if not chapter_num:
            chapter_num = 1
        if action == "revise" or _is_revision(normalized):
            return _handle_revision("writer", instruction, chapter_num)
        return _handle_writer(chapter_num, instruction, revise=False)

    if target in {"architect", "profiler", "weaver"}:
        if target in {"profiler", "weaver"} and not has_bible:
             return _handle_step("architect", f"【系统强制路由】请先生成 Series Bible。用户原指令：{instruction}")

        if action == "revise" or _is_revision(normalized):
            return _handle_revision(target, instruction, None)
        return _handle_step(target, instruction)

    if target == "slicer" or "切片" in normalized:
        if not range_info:
            range_info = intent.get("range") if isinstance(intent, dict) else None
        if range_info and range_info.get("start") and range_info.get("end"):
            return _handle_slicer(range_info["start"], range_info["end"], instruction)
        if chapter_num:
            return _handle_slicer(chapter_num, chapter_num, instruction)
        return {"agent_id": "guide", "reply": "请给出切片范围，比如 CH1-CH5。"}

    # 无法确定目标时，自动执行下一个流程步骤
    next_step = _get_next_pipeline_step()
    if next_step:
        return _handle_step(next_step, instruction)

    return {"agent_id": "guide", "reply": "所有流程已完成！需要继续调整设定或补写内容吗？"}

def _extract_setup_intent(message: str) -> Optional[Dict[str, Any]]:
    prompt = _load_prompt("setup_intent.txt")
    if not prompt:
        return None
    try:
        raw = llm.call_text("guide", prompt, f"【用户输入】\n{message}", model_id=state.models.get("guide"))
        return _safe_json_loads(raw)
    except Exception:
        return None

def _get_next_pipeline_step() -> Optional[str]:
    """根据当前状态返回下一个流程步骤
    
    流程顺序：architect (bible) → weaver (outline) → profiler (characters) → writer
    """
    if not _read_project_file("series_bible.txt"):
        return "architect"
    if not _read_project_file("outline.jsonl"):
        return "weaver"
    if not _read_project_file("characters.txt"):
        return "profiler"
    # 检查是否需要写章节
    next_ch = _next_missing_chapter()
    if next_ch:
        return "writer"
    return None


def _handle_continue() -> Dict[str, str]:
    if not _read_project_file("series_bible.txt"):
        return _handle_step("architect", "请继续生成 Series Bible。")
    if not _read_project_file("outline.jsonl"):
        return _handle_step("weaver", "请继续生成章节目录。")
    if not _read_project_file("characters.txt"):
        return _handle_step("profiler", "请继续生成角色档案。")
    next_ch = _next_missing_chapter()
    if not next_ch:
        return {"agent_id": "guide", "reply": "章节已生成完毕。要不要再调整设定或补写番外？"}
    return _handle_writer(next_ch, "继续生成下一章", revise=False)


def _handle_step(step: str, instruction: str) -> Dict[str, str]:
    try:
        if step == "architect":
            content = pipeline.run_architect(extra_instruction=instruction)
        elif step == "profiler":
            content = pipeline.run_profiler(extra_instruction=instruction)
        elif step == "weaver":
            content = pipeline.run_weaver(extra_instruction=instruction)
        else:
            return {"agent_id": "guide", "reply": "暂不支持该步骤。"}
        
        if step == "architect":
            _sync_spec_from_bible(content)
            
        state.set_flow_stage(step)
        reply = _append_handoff(step, content)
        
        response = {"agent_id": step, "reply": reply, "dispatch_message": instruction}
        
        # AUTO-FLOW TRIGGER: 
        # Enable auto-gen for these steps to support "Continuous Generation"
        if step in {"weaver", "profiler", "writer"}:
             response["trigger_auto_gen"] = True
             
        return response

    except Exception as exc:
        return {"agent_id": "guide", "reply": f"执行失败：{exc}"}


def _handle_revision(target: str, message: str, chapter_num: Optional[int]) -> Dict[str, str]:
    try:
        content = _revise_with_agent(target, message, chapter_num=chapter_num)
        reply = _append_handoff(target, content)
        return {"agent_id": target, "reply": reply, "dispatch_message": message}
    except Exception as exc:
        return {"agent_id": "guide", "reply": f"修订失败：{exc}"}


def _handle_writer(chapter_num: int, message: str, revise: bool) -> Dict[str, str]:
    try:
        if revise:
            content = _revise_with_agent("writer", message, chapter_num=chapter_num)
        else:
            content = pipeline.run_writer(chapter_num, extra_instruction=message)
        state.set_flow_stage("writer")
        reply = _append_handoff("writer", content)
        return {"agent_id": "writer", "reply": reply, "dispatch_message": message}
    except Exception as exc:
        return {"agent_id": "guide", "reply": f"写作失败：{exc}"}


def _handle_slicer(start_ch: int, end_ch: int, message: str) -> Dict[str, str]:
    try:
        slices = pipeline.run_slicer(start_ch, end_ch, extra_instruction=message)
        reply = json.dumps(slices, ensure_ascii=False, indent=2)
        return {"agent_id": "slicer", "reply": reply, "dispatch_message": message}
    except Exception as exc:
        return {"agent_id": "guide", "reply": f"切片失败：{exc}"}


def _revise_with_agent(agent_id: str, message: str, chapter_num: Optional[int] = None) -> str:
    agent = agent_map()[agent_id]
    system_prompt = _load_prompt(agent.prompt_file)
    context = _build_agent_context(agent_id)
    extra = ""
    if agent_id == "writer" and chapter_num:
        slice_obj = pipeline._find_slice(chapter_num)
        if slice_obj:
            extra = f"\n【章节切片】\n{json.dumps(slice_obj, ensure_ascii=False, indent=2)}\n"
    user_prompt = (
        f"{context}\n"
        f"{extra}\n"
        f"【用户修订要求】\n{message}\n\n"
        "请输出更新后的完整内容。"
    )
    content = llm.call_text(agent_id, system_prompt, user_prompt,
                            model_id=state.models.get(agent_id) or None)

    if agent_id == "architect":
        _write_project_file("series_bible.txt", content)
    elif agent_id == "profiler":
        _write_project_file("characters.txt", content)
    elif agent_id == "weaver":
        _write_project_file("outline.jsonl", content)
    elif agent_id == "writer" and chapter_num:
        chapters_dir = state.get_project_dir() / "chapters"
        matches = list(chapters_dir.glob(f"CH{chapter_num:04d}_*.txt"))
        if matches:
            matches[0].write_text(content, encoding="utf-8")
        else:
            title = f"chapter_{chapter_num}"
            filename = pipeline._chapter_filename(chapter_num, title)
            _write_project_file(f"chapters/{filename}", content)
        state.set_flow_stage("writer")
        
    if agent_id == "architect":
        _sync_spec_from_bible(content)

    return content


def _run_agent_chat(agent_id: str, message: str, history: str, explicit: bool) -> str:
    agent = agent_map()[agent_id]
    system_prompt = _load_prompt(agent.prompt_file)
    context = _build_agent_context(agent_id)
    user_prompt = (
        f"{context}\n"
        f"【Conversation History】\n{history}\n\n"
        f"【User Latest Input】\n{message}\n"
    )
    content = llm.call_text(agent_id, system_prompt, user_prompt,
                            model_id=state.models.get(agent_id) or None)
    return content if explicit else _truncate(content, 1200)


def _call_intent(message: str) -> Dict[str, Any]:
    prompt = _load_prompt("intent.txt")
    status = (
        f"【Current Phase】{state.flow_stage}\n"
        f"【Existing Assets】Series Bible: {'Yes' if _read_project_file('series_bible.txt') else 'No'} | "
        f"Character Profile: {'Yes' if _read_project_file('characters.txt') else 'No'} | "
        f"Chapter Outline: {'Yes' if _read_project_file('outline.jsonl') else 'No'}"
    )
    user_prompt = f"{state.spec.to_prompt()}\n{status}\n【User Input】\n{message}"
    try:
        raw = llm.call_text("intent", prompt, user_prompt,
                            model_id=state.models.get("intent") or None)
        return _safe_json_loads(raw)
    except Exception:
        return {}


def _infer_agent_by_keywords(message: str) -> Optional[str]:
    keywords = {
        "architect": ["Structure", "World", "Setting", "Series Bible", "架构", "世界观", "设定"],
        "profiler": ["Character", "Profile", "Persona", "角色", "人物"],
        "weaver": ["Outline", "Chapter List", "章节目录", "大纲"],
        "writer": ["Content", "Chapter", "Write", "Continue", "正文", "章节", "写", "创作"],
    }
    for agent_id, keys in keywords.items():
        if any(key in message for key in keys):
            return agent_id
    return None


def _parse_chapter_number(message: str) -> Optional[int]:
    match = re.search(r"CH\\s*(\\d+)", message, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"第\\s*(\\d+)\\s*章", message)
    if match:
        return int(match.group(1))
    return None


def _parse_chapter_range(message: str) -> Optional[Dict[str, int]]:
    match = re.search(r"CH\\s*(\\d+)\\s*[-~到]\\s*CH?\\s*(\\d+)", message, re.IGNORECASE)
    if match:
        return {"start": int(match.group(1)), "end": int(match.group(2))}
    match = re.search(r"(\\d+)\\s*[-~到]\\s*(\\d+)\\s*章", message)
    if match:
        return {"start": int(match.group(1)), "end": int(match.group(2))}
    return None


def _next_missing_chapter() -> Optional[int]:
    spec_total = state.spec.chapters
    chapters_dir = state.get_project_dir() / "chapters"
    existing = set()
    for file in chapters_dir.glob("CH*.txt"):
        try:
            num = int(file.stem.split("_")[0].replace("CH", ""))
            existing.add(num)
        except ValueError:
            continue
    for num in range(1, spec_total + 1):
        if num not in existing:
            return num
    return None


def _latest_chapter_number() -> Optional[int]:
    chapters_dir = state.get_project_dir() / "chapters"
    chapters = []
    for file in chapters_dir.glob("CH*.txt"):
        try:
            num = int(file.stem.split("_")[0].replace("CH", ""))
            chapters.append(num)
        except ValueError:
            continue
    return max(chapters) if chapters else None


def _is_continue(message: str) -> bool:
    keywords = ["继续", "下一步", "next", "推进", "往下", "开始", "走起"]
    return any(key in message for key in keywords)


def _is_revision(message: str) -> bool:
    keywords = ["修改", "调整", "优化", "完善", "不满意", "不好", "修", "重写", "改一下", "重新", "换成", "改成"]
    return any(key in message for key in keywords)


def _safe_json_loads(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except Exception:
                return {}
    return {}


def _append_handoff(agent_id: str, content: str) -> str:
    if agent_id == "architect":
        # Recite Spec and Request Confirmation
        spec = state.spec
        summary = (
            f"【已确认规格】\n"
            f"- 书名：{spec.title or '待定'}\n"
            f"- 核心创意：{spec.idea or '待定'}\n"
            # f"- 预计章节：{spec.chapters} 章\n"
        )
        tail = (
            "\n\n——\n"
            f"{summary}\n"
            "如果没有问题，我将为您生成整本小说（包括大纲、角色和正文）。\n"
            "请确认是否满意？（输入“确认”/“开始”/“Auto Write”即可开始）"
        )
        return f"{content}{tail}"
    
    # Other agents can keep simple or no handoff if automated
    next_step = {
        "profiler": "章节目录（Weaver）",
        "weaver": "开始写作（Writer）",
        "writer": "继续下一章或精修本章",
    }
    if agent_id not in next_step:
        return content
        
    # For others, maybe simplified
    tail = (
        "\n\n——\n"
        f"下一步：{next_step[agent_id]}。"
    )
    return f"{content}{tail}"


def _write_project_file(relative: str, content: str) -> None:
    path = state.get_project_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _sync_spec_from_bible(content: str) -> None:
    """Extracts title and idea from Series Bible to update project spec."""
    import re
    
    # Regex to find title line: 【书名】Title or 书名：Title
    # Clean up markdown like **Title** or 《Title》
    title_match = re.search(r"(?:【书名】|书名[:：])\s*(.*)", content)
    idea_match = re.search(r"(?:【核心Logline】|核心创意[:：])\s*(.*)", content)
    
    updates = {}
    if title_match:
        raw_title = title_match.group(1).strip()
        # Remove common markdown/novel wrappers
        clean_title = re.sub(r"[\*《》#\[\]]", "", raw_title).strip()
        if clean_title:
             updates["title"] = clean_title

    if idea_match:
        raw_idea = idea_match.group(1).strip()
        clean_idea = re.sub(r"[\*#]", "", raw_idea).strip()
        if clean_idea:
             updates["idea"] = clean_idea
    
    if updates:
        state.update_spec(updates)
