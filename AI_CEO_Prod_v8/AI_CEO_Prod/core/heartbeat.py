from __future__ import annotations

import asyncio
import datetime as dt
import logging

from config import SettingsStore
from core.learning import generate_suggestions
from core.task_queue import resume_ready_tasks
from database import Approval, SessionLocal, Task, WorkerDevice

logger = logging.getLogger("heartbeat")


class Heartbeat:
    def __init__(self, broadcast, ceo) -> None:
        self.broadcast = broadcast
        self.ceo = ceo
        self.running = False

    async def start(self) -> None:
        self.running = True
        while self.running:
            try:
                with SessionLocal() as db:
                    now = dt.datetime.utcnow()
                    for device in db.query(WorkerDevice).all():
                        age = (now - (device.last_seen or now)).total_seconds()
                        device.is_online = age < 90
                        device.status = "online" if device.is_online else "offline"
                    resumed = resume_ready_tasks(db)
                    auto_approve = bool(SettingsStore.get(db, "AUTO_APPROVE", False))
                    if auto_approve:
                        for approval in db.query(Approval).filter_by(status="pending").all():
                            approval.status = "approved"
                            approval.reviewer = "system:auto"
                            approval.approved_at = now
                            db.commit()
                            asyncio.create_task(self.ceo.execute_task(approval.task_id, reviewer="system:auto"))
                    for task_id in resumed:
                        task = db.query(Task).filter_by(id=task_id).first()
                        if task and task.requires_approval:
                            task.status = "pending_approval"
                        elif task:
                            asyncio.create_task(self.ceo.execute_task(task.id, reviewer="system:resume"))
                    new_suggestions = generate_suggestions(db)
                    db.commit()
                await self.broadcast({"type": "hb", "time": dt.datetime.utcnow().strftime("%H:%M:%S"), "resumed": resumed, "new_suggestions": len(new_suggestions)})
                await asyncio.sleep(8)
            except Exception as exc:
                logger.exception("Heartbeat failure: %s", exc)
                await asyncio.sleep(5)
