from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytesseract
from PIL import Image
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

import integrations as intg
from config import PUBLIC_DEFAULTS, SettingsStore
from core.audit import log_action
from core.ceo_agent import CEOAgent
from core.device_control import control_device
from core.heartbeat import Heartbeat
from core.learning import approve_suggestion_as_skill, graph_snapshot, record_event, search_to_skill
from core.memory import VectorMemory
from core.provider_switch import choose_provider, is_online
from core.rate_limit import check_rate_limit
from core.skills import create_skill, list_skills, rollback_skill, update_skill
from core.supabase_sync import push_event
from core.voice import VoiceEngine
from database import Agent, Approval, AuditLog, AutomationSuggestion, Capture, Invoice, Project, ProviderHealth, SessionLocal, SkillVersion, Task, User, WorkerCommand, WorkerDevice, init_db, uid
from security import admin_user, clear_auth_cookie, current_user, get_db, hash_password, issue_session, set_auth_cookie, verify_password, websocket_user

logger = logging.getLogger("api")
BASE_DIR = Path(__file__).resolve().parent.parent
CAPTURE_DIR = BASE_DIR / "captures"
CAPTURE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="AI CEO Production v8")
app.add_middleware(
    CORSMiddleware,
    allow_origins=PUBLIC_DEFAULTS["ALLOWED_ORIGINS"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/chrome_ext", StaticFiles(directory=str(BASE_DIR / "chrome_ext")), name="chrome_ext")

@app.middleware("http")
async def guard_and_audit(request: Request, call_next):
    client = request.client.host if request.client else "unknown"
    if not check_rate_limit(client, limit=120, window_seconds=60):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    response = await call_next(request)
    try:
        with SessionLocal() as db:
            log_action(db, client, f"http:{request.method}", request.url.path, status=str(response.status_code), detail={})
    except Exception:
        pass
    return response

mem = VectorMemory()
ceo = CEOAgent(mem)
voice = VoiceEngine()
ws_clients: set[WebSocket] = set()
heartbeat_task: asyncio.Task | None = None


async def broadcast(data: Dict[str, Any]) -> None:
    msg = json.dumps(data, default=str)
    stale = []
    for ws in list(ws_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            stale.append(ws)
    for ws in stale:
        ws_clients.discard(ws)
    try:
        with SessionLocal() as db:
            push_event(db, data.get("type", "broadcast"), data)
    except Exception:
        pass


@app.on_event("startup")
async def on_startup() -> None:
    global heartbeat_task
    init_db()
    if heartbeat_task is None:
        heartbeat_task = asyncio.create_task(Heartbeat(broadcast, ceo).start())


@app.get("/health")
def health(db: Session = Depends(get_db)) -> Dict[str, Any]:
    provider = choose_provider(db)
    return {"status": "ok", "internet": is_online(), "provider": provider, "features": ["heartbeat", "hybrid", "skills", "queue", "devices"]}


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((BASE_DIR / "static" / "index.html").read_text(encoding="utf-8"))


@app.get("/api/auth/status")
def auth_status(request: Request, db: Session = Depends(get_db)) -> Dict[str, Any]:
    setup_required = db.query(User).count() == 0
    authenticated = False
    username = None
    if not setup_required:
        try:
            user = current_user(request, db)
            authenticated = True
            username = user.username
        except Exception:
            authenticated = False
    return {"setup_required": setup_required, "authenticated": authenticated, "username": username}


@app.post("/api/auth/bootstrap")
def bootstrap(payload: dict, response: Response, db: Session = Depends(get_db)) -> Dict[str, Any]:
    if db.query(User).count() > 0:
        raise HTTPException(status_code=400, detail="Bootstrap already completed")
    username = str(payload.get("username", "admin")).strip()
    password = str(payload.get("password", "")).strip()
    if len(username) < 3 or len(password) < 12:
        raise HTTPException(status_code=400, detail="Username must be 3+ chars and password 12+ chars")
    user = User(username=username, password_hash=hash_password(password), is_admin=True, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    set_auth_cookie(response, issue_session(user))
    return {"status": "created", "username": username}


@app.post("/api/auth/login")
def login(payload: dict, response: Response, db: Session = Depends(get_db)) -> Dict[str, Any]:
    user = db.query(User).filter_by(username=str(payload.get("username", "")).strip(), is_active=True).first()
    if not user or not verify_password(str(payload.get("password", "")).strip(), user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    set_auth_cookie(response, issue_session(user))
    return {"status": "ok", "username": user.username}


@app.post("/api/auth/logout")
def logout(response: Response, user: User = Depends(current_user)) -> Dict[str, str]:
    clear_auth_cookie(response)
    return {"status": "logged_out"}


@app.websocket("/ws")
async def ws(socket: WebSocket):
    try:
        await websocket_user(socket)
    except RuntimeError:
        return
    await socket.accept()
    ws_clients.add(socket)
    try:
        while True:
            incoming = json.loads(await socket.receive_text())
            if incoming.get("cmd"):
                result = await ceo.run(incoming["cmd"], project_id=incoming.get("project_id"), agent_id=incoming.get("agent_id"), source_channel=incoming.get("source_channel", "dashboard"))
                await socket.send_text(json.dumps({"type": "resp", "data": result}))
    except Exception:
        pass
    finally:
        ws_clients.discard(socket)


@app.post("/api/command")
async def command(payload: dict, user: User = Depends(current_user)) -> Dict[str, Any]:
    source_channel = payload.get("source_channel", "dashboard")
    result = await ceo.run(payload.get("cmd", ""), project_id=payload.get("project_id"), agent_id=payload.get("agent_id"), source_channel=source_channel)
    log_action(db, user.username, "command", result.get("tid", ""), detail={"source_channel": source_channel})
    await broadcast({"type": "task_update", "data": result})
    return result


@app.post("/api/stt")
async def stt(file: UploadFile = File(...), user: User = Depends(current_user)) -> Dict[str, str]:
    suffix = Path(file.filename or "audio.webm").suffix or ".webm"
    temp_path = Path(tempfile.gettempdir()) / f"ai_ceo_{uid()}{suffix}"
    temp_path.write_bytes(await file.read())
    try:
        text = await voice.transcribe(str(temp_path))
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass
    return {"text": text}


@app.get("/api/tts")
async def tts(text: str = "", v: str = "en-US-GuyNeural", user: User = Depends(current_user)):
    if not text.strip():
        raise HTTPException(status_code=400, detail="Text required")
    return StreamingResponse(io.BytesIO(await voice.speak(text[:1200], v)), media_type="audio/mpeg")


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(admin_user)) -> Dict[str, Any]:
    return SettingsStore.public_payload(db)


@app.post("/api/settings")
def save_settings(payload: dict, db: Session = Depends(get_db), user: User = Depends(admin_user)) -> Dict[str, str]:
    SettingsStore.update_many(db, payload)
    return {"status": "saved"}


@app.get("/api/provider/status")
def provider_status(db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    rows = db.query(ProviderHealth).order_by(ProviderHealth.updated.desc()).all()
    selected = choose_provider(db)
    return {"selected": selected, "rows": [{"provider": r.provider, "status": r.status, "latency_ms": r.latency_ms, "last_error": r.last_error, "updated": r.updated.isoformat() if r.updated else None} for r in rows]}


@app.get("/api/tasks")
def get_tasks(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(Task).order_by(Task.created.desc()).all()
    return [{"id": t.id, "d": t.description, "p": t.project_id, "s": t.status, "sc": t.score, "a": t.agent_id, "td": t.target_device, "preview": t.preview} for t in rows]


@app.get("/api/tasks/{task_id}/preview")
def task_preview(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    task = db.query(Task).filter_by(id=task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"id": task.id, "description": task.description, "preview": task.preview or {}, "result": task.result, "status": task.status}


@app.get("/api/approvals")
def get_approvals(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(Approval).filter_by(status="pending").order_by(Approval.created.desc()).all()
    return [{"id": a.id, "tid": a.task_id, "d": a.description, "s": a.status} for a in rows]


@app.post("/api/approve")
async def approve(payload: dict, user: User = Depends(admin_user)) -> Dict[str, Any]:
    task_id = payload.get("task_id")
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id required")
    result = await ceo.approve_and_run(task_id, reviewer=user.username)
    log_action(db, user.username, "approve_task", task_id, detail={})
    await broadcast({"type": "task_update", "data": result})
    return result


@app.get("/api/projects")
def get_projects(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(Project).order_by(Project.created.desc()).all()
    return [{"id": p.id, "n": p.name, "i": p.instructions, "k": p.kb, "s": p.status} for p in rows]


@app.post("/api/projects")
def add_project(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, str]:
    project = Project(id=uid(), name=payload["n"], instructions=payload.get("i", ""), kb=payload.get("k", {}))
    db.add(project)
    db.commit()
    return {"status": "created", "id": project.id}


@app.put("/api/projects/{project_id}")
def update_project(project_id: str, payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, str]:
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.name = payload.get("n", project.name)
    project.instructions = payload.get("i", project.instructions)
    if "k" in payload:
        project.kb = payload["k"]
    project.status = payload.get("s", project.status)
    db.commit()
    return {"status": "updated"}


@app.get("/api/agents")
def get_agents(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(Agent).order_by(Agent.created.desc()).all()
    return [{"id": a.id, "n": a.name, "r": a.role, "sk": a.skills, "p": a.project, "s": a.status} for a in rows]


@app.post("/api/agents")
async def add_agent(payload: dict, user: User = Depends(current_user)) -> Dict[str, Any]:
    return await ceo.spawn_agent(payload["n"], payload.get("r", "worker"), payload.get("sk", []), payload.get("p"))


@app.get("/api/skills")
def get_skills(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = list_skills(db)
    return [{"id": s.id, "name": s.name, "description": s.description, "type": s.skill_type, "version": s.current_version, "source": s.source, "definition": s.definition} for s in rows]


@app.post("/api/skills")
def add_skill(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    skill = create_skill(db, payload["name"], payload.get("description", ""), payload.get("skill_type", "workflow"), payload.get("definition", {}), payload.get("source", "manual"))
    return {"status": "created", "id": skill.id}


@app.put("/api/skills/{skill_id}")
def edit_skill(skill_id: str, payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    skill = update_skill(db, skill_id, payload.get("definition", {}), payload.get("notes", "updated"))
    return {"status": "updated", "version": skill.current_version}


@app.post("/api/skills/{skill_id}/rollback")
def rollback(skill_id: str, payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    skill = rollback_skill(db, skill_id, int(payload.get("version", 1)))
    return {"status": "rolled_back", "version": skill.current_version}


@app.get("/api/skills/{skill_id}/versions")
def skill_versions(skill_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(SkillVersion).filter_by(skill_id=skill_id).order_by(SkillVersion.version.desc()).all()
    return [{"version": r.version, "notes": r.notes, "definition": r.definition} for r in rows]


@app.get("/api/automations/suggestions")
def automation_suggestions(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(AutomationSuggestion).order_by(AutomationSuggestion.updated.desc()).all()
    return [{"id": s.id, "title": s.title, "description": s.description, "confidence": s.confidence, "status": s.status, "linked_skill_id": s.linked_skill_id} for s in rows]


@app.post("/api/automations/suggestions/{suggestion_id}/approve")
def approve_suggestion(suggestion_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    return approve_suggestion_as_skill(db, suggestion_id)


@app.post("/api/search-to-skill")
def search_skill(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    skill = search_to_skill(db, payload.get("query", ""), payload.get("notes", ""))
    return {"status": "created", "skill_id": skill.id, "name": skill.name}


@app.post("/api/learn/event")
def learn_event(payload: dict, request: Request, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    if not authorization:
        try:
            current_user(request, db)
        except Exception:
            raise HTTPException(status_code=401, detail="Auth required")
    row = record_event(db, payload.get("source_device", "unknown"), payload.get("source_type", "desktop"), payload.get("event_type", "generic"), payload.get("content", ""), payload.get("meta", {}))
    return {"status": "recorded", "id": row.id}


@app.get("/api/learn/graph")
def learn_graph(db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, Any]:
    return graph_snapshot(db)


@app.get("/api/devices")
def devices(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    rows = db.query(WorkerDevice).order_by(WorkerDevice.updated.desc()).all()
    return [{"id": d.id, "name": d.name, "type": d.device_type, "status": d.status, "online": d.is_online, "last_seen": d.last_seen.isoformat() if d.last_seen else None, "capabilities": d.capabilities, "meta": d.metadata_json} for d in rows]


@app.post("/api/devices")
def add_device(payload: dict, db: Session = Depends(get_db), user: User = Depends(admin_user)) -> Dict[str, Any]:
    device = WorkerDevice(id=uid(), name=payload["name"], device_type=payload.get("device_type", "desktop"), capabilities=payload.get("capabilities", []), wol_mac=payload.get("wol_mac", ""), wol_broadcast=payload.get("wol_broadcast", PUBLIC_DEFAULTS.get("WOL_BROADCAST", "255.255.255.255")), relay_url=payload.get("relay_url", ""), smart_plug_url=payload.get("smart_plug_url", ""), smart_plug_token=payload.get("smart_plug_token", ""), amt_host=payload.get("amt_host", ""), amt_user=payload.get("amt_user", ""), amt_pass=payload.get("amt_pass", ""), notes=payload.get("notes", ""))
    db.add(device)
    db.commit()
    return {"status": "created", "id": device.id, "token": device.auth_token}


@app.post("/api/devices/{device_id}/control")
def device_control(device_id: str, payload: dict, db: Session = Depends(get_db), user: User = Depends(admin_user)) -> Dict[str, Any]:
    return control_device(db, device_id, payload.get("action", "wake"), payload.get("payload", {}))


@app.post("/api/worker/heartbeat")
def worker_heartbeat(payload: dict, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    device = None
    device_id = payload.get("device_id")
    if device_id:
        device = db.query(WorkerDevice).filter_by(id=device_id).first()
    if not device:
        device = WorkerDevice(id=uid(), name=payload.get("name", "Unnamed Worker"), device_type=payload.get("device_type", "desktop"), capabilities=payload.get("capabilities", []))
        db.add(device)
        db.commit()
        db.refresh(device)
    if authorization and device.auth_token and authorization.replace("Bearer ", "") != device.auth_token:
        raise HTTPException(status_code=401, detail="Invalid worker token")
    device.name = payload.get("name", device.name)
    device.device_type = payload.get("device_type", device.device_type)
    device.capabilities = payload.get("capabilities", device.capabilities)
    device.metadata_json = payload.get("meta", device.metadata_json)
    device.is_online = True
    device.status = "online"
    from datetime import datetime
    device.last_seen = datetime.utcnow()
    db.commit()
    push_event(db, "worker_heartbeat", {"device_id": device.id, "name": device.name, "status": device.status})
    return {"status": "ok", "device_id": device.id, "token": device.auth_token}


@app.get("/api/worker/commands")
def worker_commands(device_id: str, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> list[Dict[str, Any]]:
    device = db.query(WorkerDevice).filter_by(id=device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if authorization and device.auth_token and authorization.replace("Bearer ", "") != device.auth_token:
        raise HTTPException(status_code=401, detail="Invalid worker token")
    rows = db.query(WorkerCommand).filter_by(device_id=device_id, status="queued").order_by(WorkerCommand.created.asc()).all()
    return [{"id": r.id, "action": r.action, "payload": r.payload} for r in rows]


@app.post("/api/worker/commands/result")
def worker_command_result(payload: dict, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    cmd = db.query(WorkerCommand).filter_by(id=payload.get("command_id")).first()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    cmd.status = "completed"
    cmd.result = json.dumps(payload.get("result", {}))[:10000]
    db.commit()
    push_event(db, "worker_command_result", {"command_id": cmd.id, "device_id": cmd.device_id, "status": cmd.status})
    return {"status": "updated"}


@app.get("/api/audit")
def audit_logs(db: Session = Depends(get_db), user: User = Depends(admin_user)) -> list[Dict[str, Any]]:
    rows = db.query(AuditLog).order_by(AuditLog.created.desc()).limit(200).all()
    return [{"actor": r.actor, "action": r.action, "target": r.target, "status": r.status, "created": r.created.isoformat() if r.created else None} for r in rows]


@app.get("/api/finance")
def get_finance(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    completed = db.query(Task).filter_by(status="completed").count()
    if db.query(Invoice).count() == 0:
        db.add(Invoice(tasks=completed, amount=completed * 25.0, status="draft"))
        db.commit()
    rows = db.query(Invoice).order_by(Invoice.created.desc()).all()
    return [{"id": inv.id[:8], "tasks": inv.tasks, "amt": inv.amount, "st": inv.status} for inv in rows]


@app.get("/api/memory")
def get_memory(user: User = Depends(current_user)) -> list[Dict[str, Any]]:
    return mem.latest(limit=40)


@app.post("/api/memory/prune")
def prune_memory(user: User = Depends(admin_user)) -> Dict[str, Any]:
    return {"status": "pruned", "deleted": mem.prune(0.5)}


@app.post("/api/test_int")
def test_integration(payload: dict, db: Session = Depends(get_db), user: User = Depends(admin_user)) -> Dict[str, Any]:
    cfg = SettingsStore.provider_bundle(db)
    kind = payload.get("type")
    gjson = cfg.get("GOOGLE_SERVICE_ACCOUNT_JSON", "") or cfg.get("SHEETS_SERVICE_ACCOUNT_JSON", "")
    if kind == "wa":
        return intg.test_wa(cfg.get("WA_TOKEN", ""), cfg.get("WA_PHONE", ""), payload.get("to", ""))
    if kind == "tg":
        return intg.test_tg(cfg.get("TG_TOKEN", ""), payload.get("to", ""))
    if kind == "email":
        return intg.test_email(cfg.get("EMAIL_USER", ""), cfg.get("EMAIL_PASS", ""), cfg.get("EMAIL_HOST", "smtp.gmail.com"), int(cfg.get("EMAIL_PORT", 465)), payload.get("to", ""))
    if kind == "sheets":
        return intg.test_sheets(gjson, payload.get("sheet_id", ""), payload.get("data", ["Test Row"]))
    if kind == "calendar":
        return intg.test_calendar(gjson, payload.get("calendar_id") or cfg.get("CALENDAR_ID", "primary"))
    raise HTTPException(status_code=400, detail="Unknown integration type")


def _ocr_from_data_url(data_url: str) -> tuple[str, str]:
    header, encoded = data_url.split(",", 1)
    ext = "png" if "png" in header else "jpg"
    raw = base64.b64decode(encoded)
    image_path = CAPTURE_DIR / f"{uid()}.{ext}"
    image_path.write_bytes(raw)
    text = ""
    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(raw))).strip()
    except Exception as exc:
        text = f"OCR unavailable: {exc}"
    return str(image_path), text[:4000]


@app.post("/api/capture")
async def capture(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Dict[str, str]:
    img = payload.get("img", "")
    if not img.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Invalid image payload")
    path, ocr_text = _ocr_from_data_url(img)
    cap = Capture(url=payload.get("url", ""), image_path=path, ocr_text=ocr_text, source_device=payload.get("source_device", "desktop"))
    db.add(cap)
    db.commit()
    mem.add(f"Screen captured from {cap.url}. OCR: {ocr_text[:500]}", {"type": "screen", "relevance": 0.8, "url": cap.url, "path": path})
    record_event(db, cap.source_device, "desktop", "screen_capture", ocr_text[:800], {"url": cap.url, "path": path})
    return {"status": "logged", "ocr_preview": ocr_text[:140]}


@app.post("/api/whatsapp/webhook")
async def whatsapp_webhook(payload: dict, db: Session = Depends(get_db)) -> Dict[str, Any]:
    text = json.dumps(payload)[:5000]
    record_event(db, "whatsapp", "whatsapp", "message", text, {"watch_to_learn": True})
    lower = text.lower()
    if "/ai" in lower or "wake pc" in lower or "restart pc" in lower:
        cmd = text.split("/ai", 1)[-1].strip() if "/ai" in lower else text
        result = await ceo.run(cmd, source_channel="whatsapp")
        return {"status": "command_processed", "result": result}
    return {"status": "received"}
