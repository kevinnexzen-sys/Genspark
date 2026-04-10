from __future__ import annotations

import json
from sqlalchemy.orm import Session

from core.llm_router import LLMRouter


class Critic:
    @staticmethod
    async def evaluate(db: Session, task: str, code: str, output: dict) -> dict:
        prompt = (
            "Return strict JSON with keys score, feedback, needs_retry, improved_code. "
            "Score from 1 to 10. Only suggest improved_code when failure is fixable.\n"
            f"Task: {task}\nCode:\n{code[:5000]}\nOutput:\n{json.dumps(output)[:6000]}"
        )
        try:
            raw = await LLMRouter.chat(db, prompt, "You are a secure automation code reviewer.", json_mode=True)
            data = json.loads(raw)
            return {
                "score": int(data.get("score", 5)),
                "feedback": str(data.get("feedback", "No feedback")),
                "needs_retry": bool(data.get("needs_retry", False)),
                "improved_code": data.get("improved_code"),
            }
        except Exception as exc:
            return {
                "score": 4,
                "feedback": f"Critic fallback: {exc}",
                "needs_retry": False,
                "improved_code": None,
            }
