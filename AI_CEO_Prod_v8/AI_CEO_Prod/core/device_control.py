from __future__ import annotations

import json
import socket
import struct
import time
from typing import Any, Dict, Optional

import requests
from sqlalchemy.orm import Session

from config import SettingsStore
from database import RelayEvent, Task, WorkerCommand, WorkerDevice, uid


def device_online(device: WorkerDevice) -> bool:
    if not device.last_seen:
        return False
    return device.is_online and (time.time() - device.last_seen.timestamp()) < 90


def queue_worker_command(db: Session, device_id: str, action: str, payload: Dict[str, Any] | None = None) -> WorkerCommand:
    row = WorkerCommand(id=uid(), device_id=device_id, action=action, payload=payload or {}, status="queued")
    db.add(row)
    db.commit()
    return row


def wake_on_lan(mac: str, broadcast: str = "255.255.255.255") -> bool:
    if not mac:
        return False
    mac = mac.replace(":", "").replace("-", "")
    if len(mac) != 12:
        return False
    packet = b"FF" * 6 + (mac.encode() * 16)
    data = b""
    for i in range(0, len(packet), 2):
        data += struct.pack("B", int(packet[i : i + 2], 16))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(data, (broadcast, 9))
        return True
    finally:
        sock.close()


def relay_wake(url: str, payload: Dict[str, Any]) -> bool:
    if not url:
        return False
    resp = requests.post(url, json=payload, timeout=10)
    return resp.ok


def smart_plug_power(url: str, token: str, on: bool) -> bool:
    if not url:
        return False
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.post(url, json={"power": "on" if on else "off"}, headers=headers, timeout=10)
    return resp.ok


def intel_amt_power(device: WorkerDevice, action: str) -> bool:
    # Production hook point for Intel AMT / WS-MAN integration.
    # For now, use a configurable relay URL if present in metadata_json.
    amt_relay = (device.metadata_json or {}).get("amt_relay_url", "")
    if not amt_relay:
        return False
    resp = requests.post(amt_relay, json={"host": device.amt_host, "user": device.amt_user, "pass": device.amt_pass, "action": action}, timeout=12)
    return resp.ok


def wake_device(db: Session, device: WorkerDevice) -> Dict[str, Any]:
    methods = []
    if wake_on_lan(device.wol_mac or "", device.wol_broadcast or "255.255.255.255"):
        methods.append("wol")
    relay_url = device.relay_url or SettingsStore.get(db, "CLOUD_RELAY_URL", "")
    if relay_wake(relay_url, {"device_id": device.id, "action": "wake"}):
        methods.append("cloud_relay")
    if smart_plug_power(device.smart_plug_url, device.smart_plug_token, True):
        methods.append("smart_plug")
    if intel_amt_power(device, "on"):
        methods.append("intel_amt")
    db.add(RelayEvent(id=uid(), event_type="wake_attempt", payload={"device_id": device.id, "methods": methods}))
    db.commit()
    return {"device_id": device.id, "wake_methods": methods, "success": bool(methods)}


def control_device(db: Session, device_id: str, action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    device = db.query(WorkerDevice).filter_by(id=device_id).first()
    if not device:
        raise ValueError("Device not found")
    payload = payload or {}
    if action == "wake":
        return wake_device(db, device)
    if action == "restart":
        if not device_online(device):
            wake_device(db, device)
        cmd = queue_worker_command(db, device.id, "restart", payload)
        return {"queued": True, "command_id": cmd.id, "action": action}
    if action == "shutdown":
        cmd = queue_worker_command(db, device.id, "shutdown", payload)
        return {"queued": True, "command_id": cmd.id, "action": action}
    if action == "run":
        cmd = queue_worker_command(db, device.id, "run", payload)
        return {"queued": True, "command_id": cmd.id, "action": action}
    raise ValueError("Unsupported action")


def route_task_to_device(db: Session, task: Task) -> Task:
    desktop = db.query(WorkerDevice).filter_by(device_type="desktop").order_by(WorkerDevice.last_seen.desc()).first()
    if task.target_device == "desktop" and desktop:
        task.target_worker_id = desktop.id
        if not device_online(desktop):
            wake_device(db, desktop)
            task.status = "queued"
            task.route_reason = "desktop_offline_waiting_for_wake"
        else:
            task.status = "queued"
            task.route_reason = "desktop_worker_ready"
    return task
