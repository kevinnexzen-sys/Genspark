from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = os.getenv("AI_CEO_SERVER", "http://127.0.0.1:8000")
TOKEN = os.getenv("AI_CEO_WORKER_TOKEN", "")
NAME = os.getenv("AI_CEO_WORKER_NAME", "Primary Desktop")
DEVICE_ID = os.getenv("AI_CEO_DEVICE_ID", "")


def powershell(cmd: str) -> str:
    result = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    return (result.stdout or result.stderr).strip()


def active_window_title() -> str:
    script = "Add-Type @' using System; using System.Runtime.InteropServices; public class Win { [DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); [DllImport(\"user32.dll\", SetLastError=true, CharSet=CharSet.Auto)] public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int count);} '@; $h=[Win]::GetForegroundWindow(); $sb=New-Object System.Text.StringBuilder 1024; [Win]::GetWindowText($h,$sb,$sb.Capacity) | Out-Null; $sb.ToString()"
    return powershell(script)


def post(path: str, payload: dict):
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    return requests.post(BASE + path, json=payload, headers=headers, timeout=15)


def heartbeat() -> None:
    while True:
        try:
            title = active_window_title()
            payload = {
                "device_id": DEVICE_ID,
                "name": NAME,
                "device_type": "desktop",
                "capabilities": ["watch", "voice_listen_only", "restart", "shutdown", "whatsapp_web", "chrome_control"],
                "meta": {"active_window": title, "platform": sys.platform},
            }
            post("/api/worker/heartbeat", payload)
            if title:
                post("/api/learn/event", {"source_device": DEVICE_ID or NAME, "source_type": "desktop", "event_type": "active_window", "content": title, "meta": {"watch_to_learn": True}})
            commands = requests.get(BASE + "/api/worker/commands", headers={"Authorization": f"Bearer {TOKEN}"}, params={"device_id": DEVICE_ID}, timeout=15).json()
            for cmd in commands:
                result = {"ok": True, "action": cmd["action"]}
                if cmd["action"] == "restart":
                    powershell("Restart-Computer -Force")
                elif cmd["action"] == "shutdown":
                    powershell("Stop-Computer -Force")
                elif cmd["action"] == "run":
                    result["output"] = powershell(cmd.get("payload", {}).get("command", ""))
                post("/api/worker/commands/result", {"command_id": cmd["id"], "result": result})
        except Exception:
            pass
        time.sleep(12)


if __name__ == "__main__":
    heartbeat()
