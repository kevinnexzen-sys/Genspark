from __future__ import annotations

from typing import Any, Dict, List

from playwright.async_api import async_playwright


class PlaywrightTool:
    async def run(self, steps: List[Dict[str, Any]], headless: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"steps": []}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=headless)
            page = await browser.new_page()
            try:
                for step in steps:
                    entry = {"step": step}
                    if step.get("url"):
                        await page.goto(step["url"], wait_until="networkidle")
                    elif step.get("click"):
                        await page.click(step["click"])
                    elif step.get("type"):
                        await page.fill(step["selector"], step["type"])
                    elif step.get("extract"):
                        entry["extract"] = await page.eval_on_selector(step["extract"], "el => el.innerText")
                    elif step.get("wait"):
                        await page.wait_for_timeout(int(step["wait"]))
                    elif step.get("screenshot"):
                        path = step.get("path", "playwright_capture.png")
                        await page.screenshot(path=path, full_page=True)
                        entry["screenshot_path"] = path
                    result["steps"].append(entry)
                result["status"] = "completed"
                result["title"] = await page.title()
                return result
            finally:
                await browser.close()
