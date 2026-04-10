from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from database import Skill, SkillVersion, uid


def list_skills(db: Session) -> List[Skill]:
    return db.query(Skill).order_by(Skill.updated.desc()).all()


def create_skill(db: Session, name: str, description: str, skill_type: str, definition: Dict[str, Any], source: str = "manual") -> Skill:
    skill = Skill(id=uid(), name=name, description=description, skill_type=skill_type, definition=definition, current_version=1, source=source)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    db.add(SkillVersion(id=uid(), skill_id=skill.id, version=1, definition=definition, notes="initial"))
    db.commit()
    return skill


def update_skill(db: Session, skill_id: str, definition: Dict[str, Any], notes: str = "updated") -> Skill:
    skill = db.query(Skill).filter_by(id=skill_id).first()
    if not skill:
        raise ValueError("Skill not found")
    skill.current_version += 1
    skill.definition = definition
    db.add(SkillVersion(id=uid(), skill_id=skill.id, version=skill.current_version, definition=definition, notes=notes))
    db.commit()
    return skill


def rollback_skill(db: Session, skill_id: str, version: int) -> Skill:
    skill = db.query(Skill).filter_by(id=skill_id).first()
    history = db.query(SkillVersion).filter_by(skill_id=skill_id, version=version).first()
    if not skill or not history:
        raise ValueError("Skill/version not found")
    skill.current_version += 1
    skill.definition = history.definition
    db.add(SkillVersion(id=uid(), skill_id=skill.id, version=skill.current_version, definition=history.definition, notes=f"rollback to {version}"))
    db.commit()
    return skill
