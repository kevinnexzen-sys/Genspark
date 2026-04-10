from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from database import AuditLog, uid


def log_action(db: Session, actor: str, action: str, target: str = "", status: str = "ok", detail: Dict[str, Any] | None = None) -> None:
    db.add(AuditLog(id=uid(), actor=actor or "anonymous", action=action, target=target, status=status, detail=detail or {}))
    db.commit()
