from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from database import Task, WorkerCommand, WorkerDevice


def queued_tasks(db: Session) -> List[Task]:
    return db.query(Task).filter(Task.status.in_(["queued", "waiting_for_worker"])).order_by(Task.created.asc()).all()


def pending_worker_commands(db: Session, device_id: str) -> List[WorkerCommand]:
    return db.query(WorkerCommand).filter_by(device_id=device_id, status="queued").order_by(WorkerCommand.created.asc()).all()


def resume_ready_tasks(db: Session) -> List[str]:
    online = {d.id for d in db.query(WorkerDevice).filter_by(is_online=True).all()}
    resumed = []
    for task in queued_tasks(db):
        if task.target_device == "cloud":
            task.status = "generated"
            resumed.append(task.id)
        elif task.target_worker_id and task.target_worker_id in online:
            task.status = "generated"
            resumed.append(task.id)
    db.commit()
    return resumed
