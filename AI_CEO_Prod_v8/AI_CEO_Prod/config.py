from __future__ import annotations

import json
import os
from typing import Any, Dict

from sqlalchemy.orm import Session

from database import Setting
from security import decrypt_secret, encrypt_secret

PUBLIC_DEFAULTS: Dict[str, Any] = {
    "PROVIDER": os.getenv("AI_CEO_PROVIDER", "openai"),
    "SECONDARY_PROVIDER": os.getenv("AI_CEO_SECONDARY_PROVIDER", "anthropic"),
    "TERTIARY_PROVIDER": os.getenv("AI_CEO_TERTIARY_PROVIDER", "google"),
    "MODEL": os.getenv("AI_CEO_MODEL", "gpt-4o-mini"),
    "LOCAL_URL": os.getenv("AI_CEO_LOCAL_URL", "http://localhost:11434/v1"),
    "LOCAL_MODEL": os.getenv("AI_CEO_LOCAL_MODEL", "qwen2.5:7b"),
    "OFFLINE": os.getenv("AI_CEO_OFFLINE", "false").lower() == "true",
    "AUTO_APPROVE": os.getenv("AI_CEO_AUTO_APPROVE", "false").lower() == "true",
    "DOCKER_ENABLED": os.getenv("AI_CEO_DOCKER_ENABLED", "true").lower() == "true",
    "VOICE": os.getenv("AI_CEO_VOICE", "en-US-GuyNeural"),
    "EMAIL_HOST": os.getenv("AI_CEO_EMAIL_HOST", "smtp.gmail.com"),
    "EMAIL_PORT": int(os.getenv("AI_CEO_EMAIL_PORT", "465")),
    "ALLOWED_ORIGINS": os.getenv("AI_CEO_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(","),
    "DOCKER_IMAGE": os.getenv("AI_CEO_DOCKER_IMAGE", "python:3.11-slim"),
    "EXECUTION_MODE": os.getenv("AI_CEO_EXECUTION_MODE", "balanced"),
    "CLOUD_RELAY_URL": os.getenv("AI_CEO_CLOUD_RELAY_URL", ""),
    "WOL_BROADCAST": os.getenv("AI_CEO_WOL_BROADCAST", "255.255.255.255"),
    "CALENDAR_ID": os.getenv("AI_CEO_CALENDAR_ID", "primary"),
    "SUPABASE_URL": os.getenv("AI_CEO_SUPABASE_URL", ""),
    "PHONE_WAKE_ENABLED": os.getenv("AI_CEO_PHONE_WAKE_ENABLED", "true").lower() == "true",
}

SECRET_KEYS = {
    "API_KEY",
    "SECONDARY_API_KEY",
    "TERTIARY_API_KEY",
    "WA_TOKEN",
    "WA_PHONE",
    "TG_TOKEN",
    "EMAIL_USER",
    "EMAIL_PASS",
    "SHEETS_SERVICE_ACCOUNT_JSON",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "OPENAI_BASE_URL",
    "SUPABASE_SERVICE_KEY",
    "SMART_PLUG_TOKEN",
    "PHONE_WAKE_SECRET",
    "AMT_PASS",
}


class SettingsStore:
    @staticmethod
    def _coerce(key: str, value: str) -> Any:
        if key in {"OFFLINE", "AUTO_APPROVE", "DOCKER_ENABLED", "PHONE_WAKE_ENABLED"}:
            return str(value).lower() == "true"
        if key == "EMAIL_PORT":
            return int(value)
        if key == "ALLOWED_ORIGINS":
            if isinstance(value, list):
                return value
            return [x.strip() for x in str(value).split(",") if x.strip()]
        return value

    @classmethod
    def get(cls, db: Session, key: str, default: Any = None) -> Any:
        row = db.query(Setting).filter_by(key=key).first()
        if not row:
            return PUBLIC_DEFAULTS.get(key, default)
        raw = decrypt_secret(row.value) if row.is_secret else row.value
        return cls._coerce(key, raw)

    @classmethod
    def set(cls, db: Session, key: str, value: Any) -> None:
        if value is None:
            return
        row = db.query(Setting).filter_by(key=key).first()
        is_secret = key in SECRET_KEYS
        stored = encrypt_secret(str(value)) if is_secret and str(value) else str(value)
        if row:
            row.value = stored
            row.is_secret = is_secret
        else:
            db.add(Setting(key=key, value=stored, is_secret=is_secret))
        db.commit()

    @classmethod
    def public_payload(cls, db: Session) -> Dict[str, Any]:
        payload = {k: cls.get(db, k, v) for k, v in PUBLIC_DEFAULTS.items()}
        for k in SECRET_KEYS:
            payload[f"HAS_{k}"] = bool(cls.get(db, k, ""))
        return payload

    @classmethod
    def update_many(cls, db: Session, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            if key in SECRET_KEYS:
                if str(value).strip():
                    cls.set(db, key, value)
            elif key in PUBLIC_DEFAULTS:
                if isinstance(value, (dict, list)):
                    cls.set(db, key, json.dumps(value) if key != "ALLOWED_ORIGINS" else ",".join(value))
                else:
                    cls.set(db, key, value)

    @classmethod
    def provider_bundle(cls, db: Session) -> Dict[str, Any]:
        keys = list(PUBLIC_DEFAULTS.keys()) + list(SECRET_KEYS)
        return {k: cls.get(db, k, PUBLIC_DEFAULTS.get(k)) for k in keys}
