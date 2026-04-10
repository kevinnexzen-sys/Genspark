from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Cookie, Depends, HTTPException, Request, Response, WebSocket, status
from sqlalchemy.orm import Session

from database import SessionLocal, User

INSTANCE_DIR = Path("instance")
INSTANCE_DIR.mkdir(exist_ok=True)
FERNET_FILE = INSTANCE_DIR / "fernet.key"
SESSION_EXP_HOURS = 12
COOKIE_NAME = "ai_ceo_session"


def _load_or_create_fernet_key() -> bytes:
    if FERNET_FILE.exists():
        return FERNET_FILE.read_bytes()
    key = Fernet.generate_key()
    FERNET_FILE.write_bytes(key)
    try:
        os.chmod(FERNET_FILE, 0o600)
    except OSError:
        pass
    return key


FERNET = Fernet(_load_or_create_fernet_key())


def get_session_secret() -> str:
    raw = os.getenv("AI_CEO_SESSION_SECRET")
    if raw:
        return raw
    fallback = INSTANCE_DIR / "session.key"
    if fallback.exists():
        return fallback.read_text().strip()
    token = base64.urlsafe_b64encode(os.urandom(32)).decode()
    fallback.write_text(token)
    try:
        os.chmod(fallback, 0o600)
    except OSError:
        pass
    return token


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    if not salt:
        salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, hash_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        candidate = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def issue_session(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user.id,
        "usr": user.username,
        "adm": user.is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=SESSION_EXP_HOURS)).timestamp()),
    }
    return jwt.encode(payload, get_session_secret(), algorithm="HS256")


def decode_session(token: str) -> dict:
    return jwt.decode(token, get_session_secret(), algorithms=["HS256"])


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=SESSION_EXP_HOURS * 3600,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def encrypt_secret(value: str) -> str:
    return FERNET.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return FERNET.decrypt(value.encode()).decode()
    except InvalidToken:
        return ""


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = decode_session(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    user = db.query(User).filter_by(id=payload.get("sub"), is_active=True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def websocket_user(ws: WebSocket) -> dict:
    token = ws.cookies.get(COOKIE_NAME)
    if not token:
        await ws.close(code=4401)
        raise RuntimeError("Missing websocket auth")
    try:
        return decode_session(token)
    except Exception:
        await ws.close(code=4401)
        raise RuntimeError("Invalid websocket auth")
