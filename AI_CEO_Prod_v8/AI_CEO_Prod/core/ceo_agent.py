from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from config import SettingsStore
from core.critic import Critic
from core.audit import log_action
from core.device_control import route_task_to_device
from core.learning import record_event, search_to_skill
from core.llm_router import LLMRouter
from core.memory import VectorMemory
from core.playwright_bridge import PlaywrightTool
from core.policy import validate_browser_steps, validate_python
from database import Agent, Approval, SessionLocal, Task, WorkerDevice, uid
from sandbox.executor import Executor

logger = logging.getLogger("ceo")

PLAN_SYSTEM = """
You are an AI operations CEO that creates secure automation plans.
Return strict JSON with keys:
thought, code, needs_browser, needs_approval, summary, target_device, preview.
Rules:
- target_device must be one of cloud, desktop, phone.
- Use Python only for local file/data processing.
- Never generate shell commands inside Python.
- Prefer browser steps for web actions.
- Add a small preview object describing the proposed output.
""".strip()


class CEOAgent:
    def __init__(self, mem: VectorMemory) -> None:
        self.mem = mem
        self.browser = PlaywrightTool()

    def _route_hint(self, cmd: str) -> str:
        lower = cmd.lower()
        if any(x in lower for x in ["wake pc", "restart pc", "shutdown pc", "whatsapp web", "chrome", "desktop", "file system", "watch screen"]):
            return "desktop"
        if any(x in lower for x in ["phone", "mobile"]):
            return "phone"
        return "cloud"

    def _ensure_dynamic_agent(self, db, cmd: str, parent_agent_id: Optional[str] = None) -> str:
        role = "general_worker"
        lower = cmd.lower()
        if "estimate" in lower or "invoice" in lower:
            role = "pricing_agent"
        elif "calendar" in lower:
            role = "calendar_agent"
        elif "email" in lower:
            role = "email_agent"
        elif "sheet" in lower:
            role = "sheets_agent"
        elif "whatsapp" in lower:
            role = "whatsapp_agent"
        elif "code" in lower or "app" in lower:
            role = "code_generator_agent"
        existing = db.query(Agent).filter_by(role=role, template=False).first()
        if existing:
            return existing.id
        agent = Agent(id=uid(), name=role.replace("_", " ").title(), role=role, skills=[role], template=False, parent_agent_id=parent_agent_id, status="active")
        db.add(agent)
        db.commit()
        return agent.id

    async def run(self, cmd: str, project_id: Optional[str] = None, agent_id: Optional[str] = None, source_channel: str = "dashboard") -> Dict[str, Any]:
        self.mem.add(cmd, {"type": "cmd", "relevance": 1.0})
        with SessionLocal() as db:
            record_event(db, source_channel, "channel", "command", cmd, {"project_id": project_id})
            if source_channel == "search":
                search_to_skill(db, cmd)
            context = self.mem.query(cmd, k=4)
            ctx_text = json.dumps([item["text"] for item in context])
            raw = await LLMRouter.chat(db, prompt=f"Command: {cmd}\nRelevant memory: {ctx_text}", system=PLAN_SYSTEM, json_mode=True)
            try:
                plan = json.loads(raw)
            except Exception as exc:
                raise RuntimeError(f"Planner returned invalid JSON: {exc}; raw={raw[:500]}") from exc

            dyn_agent_id = agent_id or self._ensure_dynamic_agent(db, cmd)
            target_device = plan.get("target_device") or self._route_hint(cmd)
            task = Task(
                id=uid(),
                project_id=project_id,
                agent_id=dyn_agent_id,
                description=cmd,
                status="generated",
                result=plan.get("thought", ""),
                code=plan.get("code", ""),
                use_browser=bool(plan.get("needs_browser", False)),
                requires_approval=bool(plan.get("needs_approval", True)),
                target_device=target_device,
                preview=plan.get("preview", {}),
                source_channel=source_channel,
            )
            db.add(task)
            db.commit()
            db.refresh(task)

            if task.target_device in {"desktop", "phone"}:
                route_task_to_device(db, task)
                db.commit()
            log_action(db, "ceo", "task_created", task.id, detail={"target_device": task.target_device, "source_channel": source_channel})
            if task.requires_approval and not SettingsStore.get(db, "AUTO_APPROVE", False):
                approval = Approval(id=uid(), task_id=task.id, description=cmd, code=task.code, payload={"use_browser": task.use_browser, "target_device": task.target_device}, status="pending")
                if task.status == "generated":
                    task.status = "pending_approval"
                db.add(approval)
                db.commit()
                return {"status": task.status, "tid": task.id, "thought": plan.get("thought", "Awaiting approval"), "summary": plan.get("summary", ""), "preview": task.preview, "target_device": task.target_device}
            if task.status in {"queued", "waiting_for_worker"}:
                return {"status": task.status, "tid": task.id, "thought": plan.get("thought", "Queued for device"), "summary": plan.get("summary", ""), "preview": task.preview, "target_device": task.target_device}
        return await self.execute_task(task.id, reviewer="system:auto")

    async def execute_task(self, task_id: str, reviewer: Optional[str] = None) -> Dict[str, Any]:
        with SessionLocal() as db:
            task = db.query(Task).filter_by(id=task_id).first()
            if not task:
                raise RuntimeError("Task not found")
            if task.target_device in {"desktop", "phone"}:
                task.status = "queued"
                db.commit()
                return {"status": "queued", "tid": task.id, "thought": f"Waiting for {task.target_device} worker to pick up task", "preview": task.preview}
            if reviewer:
                task.approved_by = reviewer
            task.status = "running"
            db.commit()
            cfg = SettingsStore.provider_bundle(db)
            executor = Executor(docker_enabled=bool(cfg.get("DOCKER_ENABLED", True)), image=cfg.get("DOCKER_IMAGE", "python:3.11-slim"))
            code = task.code
            use_browser = bool(task.use_browser)
            desc = task.description

        output: Dict[str, Any]
        critic: Dict[str, Any]
        try:
            if use_browser:
                steps = validate_browser_steps(code)
                output = await self.browser.run(steps)
            else:
                validate_python(code)
                output = executor.run(code)
            with SessionLocal() as db:
                critic = await Critic.evaluate(db, desc, code, output)
            retry_code = critic.get("improved_code")
            if critic.get("needs_retry") and retry_code and retry_code != code:
                with SessionLocal() as db:
                    task = db.query(Task).filter_by(id=task_id).first()
                    task.code = retry_code
                    task.retry_count += 1
                    db.commit()
                return await self.execute_task(task_id, reviewer=reviewer)
            status = "completed" if output.get("status") in {"success", "completed"} else "failed"
        except Exception as exc:
            output = {"status": "failed", "out": "", "err": str(exc)}
            critic = {"score": 1, "feedback": str(exc), "needs_retry": False, "improved_code": None}
            status = "failed"
            logger.exception("Task execution failed: %s", exc)

        with SessionLocal() as db:
            task = db.query(Task).filter_by(id=task_id).first()
            if task:
                task.status = status
                task.score = int(critic.get("score", 0))
                task.result = json.dumps({"critic": critic, "output": output})[:20000]
                db.commit()
                log_action(db, reviewer or "system", "task_executed", task.id, status=status, detail={"score": critic.get("score", 0), "target": task.target_device})
            record_event(db, task.target_device if task else "cloud", task.target_device if task else "cloud", "task_result", json.dumps(output)[:1000], {"task_id": task_id, "status": status})
        self.mem.add(f"Executed task {desc}: {critic.get('feedback', '')}", {"type": "exec", "relevance": max(float(critic.get("score", 1)) / 10.0, 0.1)})
        return {"status": status, "tid": task_id, "score": critic.get("score", 0), "thought": critic.get("feedback", "Done"), "output": output}

    async def approve_and_run(self, task_id: str, reviewer: str) -> Dict[str, Any]:
        with SessionLocal() as db:
            approval = db.query(Approval).filter_by(task_id=task_id, status="pending").first()
            if approval:
                approval.status = "approved"
                approval.reviewer = reviewer
                db.commit()
            task = db.query(Task).filter_by(id=task_id).first()
            if task:
                task.approved_by = reviewer
                db.commit()
        return await self.execute_task(task_id, reviewer=reviewer)

    async def spawn_agent(self, name: str, role: str, skills: list[str], project: Optional[str] = None) -> Dict[str, Any]:
        with SessionLocal() as db:
            agent = Agent(id=uid(), name=name, role=role, skills=skills, project=project, status="active")
            db.add(agent)
            db.commit()
        return {"status": "agent_spawned", "name": name, "role": role}
