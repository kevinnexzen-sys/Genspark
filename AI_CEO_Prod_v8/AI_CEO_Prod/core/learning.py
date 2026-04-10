from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database import AutomationSuggestion, LearningEdge, LearningEvent, Skill, SkillVersion, uid


def fingerprint(event_type: str, content: str) -> str:
    return hashlib.sha256(f"{event_type}:{content.strip().lower()}".encode()).hexdigest()[:24]


def record_event(db: Session, source_device: str, source_type: str, event_type: str, content: str, meta: Dict[str, Any] | None = None) -> LearningEvent:
    meta = meta or {}
    fp = fingerprint(event_type, content)
    row = LearningEvent(
        id=uid(),
        source_device=source_device,
        source_type=source_type,
        event_type=event_type,
        content=content,
        fingerprint=fp,
        meta=meta,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    previous = (
        db.query(LearningEvent)
        .filter(LearningEvent.source_device == source_device, LearningEvent.id != row.id)
        .order_by(desc(LearningEvent.created))
        .first()
    )
    if previous:
        src = f"{previous.event_type}:{previous.fingerprint}"
        dst = f"{row.event_type}:{row.fingerprint}"
        edge = db.query(LearningEdge).filter_by(source_node=src, target_node=dst).first()
        if not edge:
            edge = LearningEdge(id=uid(), source_node=src, target_node=dst, weight=0.0, meta={"source_device": source_device})
            db.add(edge)
        edge.weight += 1.0
        db.commit()
    return row


def generate_suggestions(db: Session) -> List[dict]:
    recent = db.query(LearningEvent).order_by(desc(LearningEvent.created)).limit(300).all()
    counts = Counter((evt.event_type, evt.fingerprint, evt.content[:120]) for evt in recent)
    made = []
    for (event_type, fp, preview), count in counts.items():
        if count < 3:
            continue
        title = f"Automate repeated {event_type} flow"
        exists = db.query(AutomationSuggestion).filter_by(title=title, status="suggested").first()
        if exists:
            continue
        suggestion = AutomationSuggestion(
            id=uid(),
            title=title,
            description=f"Detected {count} repeated {event_type} events. Preview: {preview}",
            confidence=min(0.45 + (count / 10.0), 0.95),
            source="learning",
            action={"event_type": event_type, "fingerprint": fp, "preview": preview},
            status="suggested",
        )
        db.add(suggestion)
        db.commit()
        made.append({"id": suggestion.id, "title": suggestion.title, "confidence": suggestion.confidence})
    return made


def search_to_skill(db: Session, query: str, notes: str = "") -> Skill:
    name = query[:80]
    existing = db.query(Skill).filter_by(name=name).first()
    definition = {"query": query, "notes": notes, "steps": ["search", "review", "summarize", "save"]}
    if existing:
        existing.current_version += 1
        existing.definition = definition
        db.add(SkillVersion(id=uid(), skill_id=existing.id, version=existing.current_version, definition=definition, notes="search_to_skill update"))
        db.commit()
        return existing
    skill = Skill(id=uid(), name=name, description=f"Generated from search intent: {query}", skill_type="search_skill", definition=definition, current_version=1, source="search_to_skill")
    db.add(skill)
    db.commit()
    db.add(SkillVersion(id=uid(), skill_id=skill.id, version=1, definition=definition, notes="initial from search_to_skill"))
    db.commit()
    return skill


def approve_suggestion_as_skill(db: Session, suggestion_id: str) -> dict:
    suggestion = db.query(AutomationSuggestion).filter_by(id=suggestion_id).first()
    if not suggestion:
        raise ValueError("Suggestion not found")
    suggestion.status = "approved"
    skill = Skill(
        id=uid(),
        name=suggestion.title,
        description=suggestion.description,
        skill_type="automation",
        definition=suggestion.action or {},
        current_version=1,
        source="suggestion_approval",
    )
    db.add(skill)
    db.commit()
    db.add(SkillVersion(id=uid(), skill_id=skill.id, version=1, definition=skill.definition, notes="approved from suggestion"))
    suggestion.linked_skill_id = skill.id
    db.commit()
    return {"suggestion_id": suggestion.id, "skill_id": skill.id, "name": skill.name}


def graph_snapshot(db: Session, limit: int = 120) -> dict:
    edges = db.query(LearningEdge).order_by(desc(LearningEdge.weight)).limit(limit).all()
    nodes = set()
    edge_rows = []
    for edge in edges:
        nodes.add(edge.source_node)
        nodes.add(edge.target_node)
        edge_rows.append({"source": edge.source_node, "target": edge.target_node, "weight": edge.weight, "meta": edge.meta or {}})
    return {"nodes": sorted(nodes), "edges": edge_rows}
