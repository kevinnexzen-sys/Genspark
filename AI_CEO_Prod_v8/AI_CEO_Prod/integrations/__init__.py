from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Any, Dict

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build

TIMEOUT = 20


def _google_creds(service_account_json: str):
    info = json.loads(service_account_json)
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )


def test_wa(token: str, phone: str, to: str) -> Dict[str, Any]:
    if not token or not phone or not to:
        return {"error": "Missing WhatsApp config or recipient"}
    response = requests.post(
        f"https://graph.facebook.com/v20.0/{phone}/messages",
        json={"messaging_product": "whatsapp", "to": to, "text": {"body": "Test from AI CEO"}},
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT,
    )
    return {"status": response.status_code, "body": response.json()}


def test_tg(token: str, chat_id: str) -> Dict[str, Any]:
    if not token or not chat_id:
        return {"error": "Missing Telegram config or recipient"}
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": "Test from AI CEO"},
        timeout=TIMEOUT,
    )
    return {"status": response.status_code, "body": response.json()}


def test_email(user: str, pwd: str, host: str, port: int, to: str) -> Dict[str, Any]:
    if not user or not pwd or not to:
        return {"error": "Missing email config or recipient"}
    message = EmailMessage()
    message.set_content("Test from AI CEO")
    message["Subject"] = "AI CEO test"
    message["From"] = user
    message["To"] = to
    with smtplib.SMTP_SSL(host, int(port), timeout=TIMEOUT) as smtp:
        smtp.login(user, pwd)
        smtp.send_message(message)
    return {"status": "success"}


def test_sheets(service_account_json: str, sheet_id: str, vals) -> Dict[str, Any]:
    if not service_account_json or not sheet_id:
        return {"error": "Missing Google Sheets service account JSON or sheet ID"}
    creds = _google_creds(service_account_json)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range="Sheet1!A1",
        valueInputOption="RAW",
        body={"values": [vals if isinstance(vals, list) else [vals]]},
    ).execute()
    return {"status": "success"}


def test_calendar(service_account_json: str, calendar_id: str) -> Dict[str, Any]:
    if not service_account_json:
        return {"error": "Missing Google service account JSON"}
    creds = _google_creds(service_account_json)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    events = service.events().list(calendarId=calendar_id or "primary", maxResults=5, singleEvents=True, orderBy="startTime").execute()
    return {"status": "success", "items": events.get("items", [])[:5]}
