from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
import google.generativeai as genai
from groq import AsyncGroq
from sqlalchemy.orm import Session

from config import SettingsStore
from core.provider_switch import choose_provider, provider_candidates, record_provider_health


class LLMRouter:
    @staticmethod
    async def _call_provider(provider: str, api_key: str, cfg: Dict[str, Any], prompt: str, system: str, json_mode: bool) -> str:
        model = cfg.get("MODEL", "gpt-4o-mini")
        if provider in {"ollama", "local"}:
            client = AsyncOpenAI(base_url=cfg.get("LOCAL_URL"), api_key="local")
            response = await client.chat.completions.create(
                model=cfg.get("LOCAL_MODEL", model),
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"} if json_mode else None,
            )
            return response.choices[0].message.content or ""
        if provider == "openai":
            client = AsyncOpenAI(api_key=api_key or cfg.get("API_KEY"), base_url=cfg.get("OPENAI_BASE_URL") or None)
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"} if json_mode else None,
            )
            return response.choices[0].message.content or ""
        if provider == "anthropic":
            client = AsyncAnthropic(api_key=api_key or cfg.get("SECONDARY_API_KEY") or cfg.get("API_KEY"))
            response = await client.messages.create(
                model=model,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
            )
            return response.content[0].text
        if provider == "google":
            genai.configure(api_key=api_key or cfg.get("TERTIARY_API_KEY") or cfg.get("API_KEY"))
            response = await genai.GenerativeModel(model).generate_content_async(f"{system}\n\n{prompt}")
            text = getattr(response, "text", "") or ""
            if json_mode:
                try:
                    json.loads(text)
                    return text
                except Exception:
                    return json.dumps({"text": text})
            return text
        if provider == "groq":
            client = AsyncGroq(api_key=api_key or cfg.get("API_KEY"))
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                response_format={"type": "json_object"} if json_mode else None,
            )
            return response.choices[0].message.content or ""
        raise ValueError(f"Unsupported provider: {provider}")

    @staticmethod
    async def chat(db: Session, prompt: str, system: str = "", json_mode: bool = False) -> str:
        cfg = SettingsStore.provider_bundle(db)
        preferred = choose_provider(db, prompt).get("provider", "ollama")
        chain = provider_candidates(db)
        chain.sort(key=lambda pair: 0 if pair[0] == preferred else 1)
        last_error = None
        for provider, key in chain:
            started = time.time()
            try:
                text = await LLMRouter._call_provider(provider, key, cfg, prompt, system, json_mode)
                record_provider_health(db, provider, "ok", int((time.time() - started) * 1000), "")
                return text
            except Exception as exc:
                last_error = exc
                record_provider_health(db, provider, "failed", int((time.time() - started) * 1000), str(exc))
                continue
        raise RuntimeError(f"All providers failed: {last_error}")
