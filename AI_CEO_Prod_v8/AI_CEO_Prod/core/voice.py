from __future__ import annotations

import io
from typing import Optional

import edge_tts
from faster_whisper import WhisperModel


class VoiceEngine:
    def __init__(self) -> None:
        self.stt: Optional[WhisperModel] = None
        try:
            self.stt = WhisperModel("small", compute_type="int8", device="cpu")
        except Exception:
            self.stt = None

    async def transcribe(self, path: str, language: str = "en") -> str:
        if not self.stt:
            return ""
        segments, _ = self.stt.transcribe(path, language=language)
        return " ".join(seg.text for seg in segments).strip()

    async def speak(self, text: str, voice: str = "en-US-GuyNeural") -> bytes:
        comm = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()
