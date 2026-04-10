from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import requests
from playwright.async_api import async_playwright

SERVER = os.getenv("AI_CEO_SERVER", "http://127.0.0.1:8000")
PROFILE_DIR = os.getenv("AI_CEO_CHROME_PROFILE", str(Path.home() / ".ai_ceo_whatsapp"))


async def monitor() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(PROFILE_DIR, headless=False)
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto("https://web.whatsapp.com")
        last = ""
        while True:
            try:
                text = await page.locator("div[role='textbox']").first.text_content(timeout=5000)
            except Exception:
                text = ""
            if text and text != last:
                last = text
                try:
                    requests.post(SERVER + "/api/whatsapp/webhook", json={"source": "whatsapp_web", "text": text}, timeout=10)
                except Exception:
                    pass
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(monitor())
