from __future__ import annotations

import datetime as dt
import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, JSON, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./ceo_platform.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def uid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=uid)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created = Column(DateTime, default=dt.datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    instructions = Column(Text, default="")
    kb = Column(JSON, default=dict)
    status = Column(String, default="active")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)
    description = Column(Text, nullable=False)
    status = Column(String, default="pending")
    result = Column(Text, default="")
    score = Column(Integer, default=0)
    code = Column(Text, default="")
    use_browser = Column(Boolean, default=False)
    requires_approval = Column(Boolean, default=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    target_device = Column(String, default="cloud")
    target_worker_id = Column(String, nullable=True)
    route_reason = Column(Text, default="")
    retry_count = Column(Integer, default=0)
    preview = Column(JSON, default=dict)
    source_channel = Column(String, default="dashboard")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(String, primary_key=True, default=uid)
    task_id = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String, default="pending")
    reviewer = Column(String, nullable=True)
    created = Column(DateTime, default=dt.datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)


class Agent(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    role = Column(String, default="worker")
    skills = Column(JSON, default=list)
    project = Column(String, nullable=True)
    status = Column(String, default="idle")
    template = Column(Boolean, default=False)
    parent_agent_id = Column(String, nullable=True)
    created = Column(DateTime, default=dt.datetime.utcnow)


class MemoryEntry(Base):
    __tablename__ = "memory"
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    meta = Column(JSON, default=dict)
    relevance = Column(Float, default=1.0)
    created = Column(DateTime, default=dt.datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text, default="")
    is_secret = Column(Boolean, default=False)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(String, primary_key=True, default=uid)
    tasks = Column(Integer, default=0)
    amount = Column(Float, default=0.0)
    status = Column(String, default="draft")
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    created = Column(DateTime, default=dt.datetime.utcnow)


class Capture(Base):
    __tablename__ = "captures"
    id = Column(String, primary_key=True, default=uid)
    url = Column(Text, default="")
    image_path = Column(Text, default="")
    ocr_text = Column(Text, default="")
    source_device = Column(String, default="desktop")
    created = Column(DateTime, default=dt.datetime.utcnow)


class WorkerDevice(Base):
    __tablename__ = "worker_devices"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    device_type = Column(String, default="desktop")
    status = Column(String, default="offline")
    is_online = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=dt.datetime.utcnow)
    capabilities = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    auth_token = Column(String, default=uid)
    wol_mac = Column(String, default="")
    wol_broadcast = Column(String, default="255.255.255.255")
    relay_url = Column(String, default="")
    smart_plug_url = Column(String, default="")
    smart_plug_token = Column(String, default="")
    amt_host = Column(String, default="")
    amt_user = Column(String, default="")
    amt_pass = Column(String, default="")
    notes = Column(Text, default="")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class WorkerCommand(Base):
    __tablename__ = "worker_commands"
    id = Column(String, primary_key=True, default=uid)
    device_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    status = Column(String, default="queued")
    result = Column(Text, default="")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    skill_type = Column(String, default="workflow")
    definition = Column(JSON, default=dict)
    current_version = Column(Integer, default=1)
    status = Column(String, default="active")
    source = Column(String, default="manual")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    id = Column(String, primary_key=True, default=uid)
    skill_id = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    definition = Column(JSON, default=dict)
    notes = Column(Text, default="")
    created = Column(DateTime, default=dt.datetime.utcnow)


class LearningEvent(Base):
    __tablename__ = "learning_events"
    id = Column(String, primary_key=True, default=uid)
    source_device = Column(String, default="unknown")
    source_type = Column(String, default="desktop")
    event_type = Column(String, nullable=False)
    content = Column(Text, default="")
    fingerprint = Column(String, default="")
    meta = Column(JSON, default=dict)
    created = Column(DateTime, default=dt.datetime.utcnow)


class LearningEdge(Base):
    __tablename__ = "learning_edges"
    id = Column(String, primary_key=True, default=uid)
    source_node = Column(String, nullable=False)
    target_node = Column(String, nullable=False)
    weight = Column(Float, default=1.0)
    meta = Column(JSON, default=dict)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class AutomationSuggestion(Base):
    __tablename__ = "automation_suggestions"
    id = Column(String, primary_key=True, default=uid)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    confidence = Column(Float, default=0.0)
    source = Column(String, default="learning")
    action = Column(JSON, default=dict)
    linked_skill_id = Column(String, nullable=True)
    status = Column(String, default="suggested")
    created = Column(DateTime, default=dt.datetime.utcnow)
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class ProviderHealth(Base):
    __tablename__ = "provider_health"
    id = Column(String, primary_key=True, default=uid)
    provider = Column(String, nullable=False)
    status = Column(String, default="unknown")
    latency_ms = Column(Integer, default=0)
    last_error = Column(Text, default="")
    updated = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)


class RelayEvent(Base):
    __tablename__ = "relay_events"
    id = Column(String, primary_key=True, default=uid)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, default=dict)
    created = Column(DateTime, default=dt.datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=uid)
    actor = Column(String, default="anonymous")
    action = Column(String, nullable=False)
    target = Column(String, default="")
    status = Column(String, default="ok")
    detail = Column(JSON, default=dict)
    created = Column(DateTime, default=dt.datetime.utcnow)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
