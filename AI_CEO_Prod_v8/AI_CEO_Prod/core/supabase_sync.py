from __future__ import annotations

from typing import Any, Dict

import requests
from sqlalchemy.orm import Session

from config import SettingsStore


def push_event(db: Session, event_type: str, payload: Dict[str, Any]) -> bool:
    url = SettingsStore.get(db, "SUPABASE_URL", "")
    key = SettingsStore.get(db, "SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return False
    endpoint = url.rstrip("/") + "/rest/v1/relay_events"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    resp = requests.post(endpoint, headers=headers, json={"event_type": event_type, "payload": payload}, timeout=8)
    return resp.ok
