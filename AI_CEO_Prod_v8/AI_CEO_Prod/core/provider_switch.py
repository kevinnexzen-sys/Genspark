from __future__ import annotations

import socket
import time
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from config import SettingsStore
from database import ProviderHealth


def is_online() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=1.2).close()
        return True
    except OSError:
        return False


def provider_candidates(db: Session) -> List[Tuple[str, str]]:
    cfg = SettingsStore.provider_bundle(db)
    candidates = [
        (str(cfg.get("PROVIDER", "openai")).lower(), cfg.get("API_KEY", "")),
        (str(cfg.get("SECONDARY_PROVIDER", "anthropic")).lower(), cfg.get("SECONDARY_API_KEY", "") or cfg.get("API_KEY", "")),
        (str(cfg.get("TERTIARY_PROVIDER", "google")).lower(), cfg.get("TERTIARY_API_KEY", "") or cfg.get("API_KEY", "")),
        ("ollama", "local"),
    ]
    seen = set()
    ordered = []
    for provider, key in candidates:
        if provider and provider not in seen:
            seen.add(provider)
            ordered.append((provider, key))
    return ordered


def choose_provider(db: Session, task_hint: str = "") -> Dict[str, str]:
    cfg = SettingsStore.provider_bundle(db)
    mode = str(cfg.get("EXECUTION_MODE", "balanced")).lower()
    offline_forced = bool(cfg.get("OFFLINE", False)) or not is_online()
    if offline_forced:
        return {"provider": "ollama", "reason": "offline_or_privacy"}
    if mode == "privacy" or "private" in task_hint.lower():
        return {"provider": "ollama", "reason": "privacy_mode"}
    if mode == "fast":
        for name, _ in provider_candidates(db):
            if name in {"groq", "openai", "ollama", "anthropic", "google"}:
                return {"provider": name, "reason": "fast_mode"}
    for name, _ in provider_candidates(db):
        if name:
            return {"provider": name, "reason": "primary_fallback_chain"}
    return {"provider": "ollama", "reason": "default_local"}


def record_provider_health(db: Session, provider: str, status: str, latency_ms: int = 0, last_error: str = "") -> None:
    row = db.query(ProviderHealth).filter_by(provider=provider).first()
    if not row:
        row = ProviderHealth(provider=provider)
        db.add(row)
    row.status = status
    row.latency_ms = latency_ms
    row.last_error = last_error[:1000]
    db.commit()
