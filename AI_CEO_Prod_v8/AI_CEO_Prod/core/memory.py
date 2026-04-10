from __future__ import annotations

from threading import Lock
from typing import Any, Dict, List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import desc

from database import MemoryEntry, SessionLocal


class VectorMemory:
    def __init__(self) -> None:
        self.model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
        self.index = faiss.IndexFlatIP(384)
        self.data: List[Dict[str, Any]] = []
        self.lock = Lock()
        self._rebuild()

    def _embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype="float32")
        return self.model.encode(texts, normalize_embeddings=True).astype("float32")

    def _rebuild(self) -> None:
        with self.lock:
            self.index = faiss.IndexFlatIP(384)
            with SessionLocal() as db:
                rows = db.query(MemoryEntry).order_by(MemoryEntry.id.asc()).all()
            self.data = [
                {
                    "id": r.id,
                    "text": r.content,
                    "type": r.type,
                    "relevance": r.relevance,
                    "meta": r.meta or {},
                    "created": r.created.isoformat() if r.created else None,
                }
                for r in rows
            ]
            embs = self._embed([row["text"] for row in self.data])
            if len(embs):
                self.index.add(embs)

    def add(self, text: str, meta: Dict[str, Any]) -> None:
        with SessionLocal() as db:
            row = MemoryEntry(
                type=meta.get("type", "log"),
                content=text,
                relevance=float(meta.get("relevance", 1.0)),
                meta=meta,
            )
            db.add(row)
            db.commit()
        self._rebuild()

    def query(self, text: str, k: int = 3) -> List[Dict[str, Any]]:
        with self.lock:
            if not self.data:
                return []
            emb = self._embed([text])
            distances, indices = self.index.search(emb, min(k, len(self.data)))
            result = []
            for idx, score in zip(indices[0], distances[0]):
                if 0 <= idx < len(self.data):
                    item = dict(self.data[idx])
                    item["score"] = float(score)
                    result.append(item)
            return result

    def prune(self, threshold: float = 0.5) -> int:
        with SessionLocal() as db:
            deleted = db.query(MemoryEntry).filter(MemoryEntry.relevance < threshold).delete()
            db.commit()
        self._rebuild()
        return deleted

    def latest(self, limit: int = 40) -> List[Dict[str, Any]]:
        with SessionLocal() as db:
            rows = db.query(MemoryEntry).order_by(desc(MemoryEntry.id)).limit(limit).all()
        return [
            {
                "t": row.type,
                "c": row.content[:120],
                "r": float(row.relevance),
                "meta": row.meta or {},
            }
            for row in rows
        ]
