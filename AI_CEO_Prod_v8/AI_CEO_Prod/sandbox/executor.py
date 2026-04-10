from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict

import docker
from docker.errors import DockerException


class Executor:
    def __init__(self, docker_enabled: bool = True, image: str = "python:3.11-slim") -> None:
        self.docker_enabled = docker_enabled
        self.image = image
        self.client = None
        if docker_enabled:
            try:
                self.client = docker.from_env()
            except DockerException:
                self.client = None

    def run(self, code: str, timeout: int = 30) -> Dict[str, str]:
        if self.client:
            try:
                return self._run_docker(code, timeout)
            except Exception as exc:
                return {"status": "failed", "out": "", "err": f"Docker execution failed: {exc}"}
        return self._run_local(code, timeout)

    def _run_local(self, code: str, timeout: int) -> Dict[str, str]:
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(code)
            path = tmp.name
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"PATH": os.environ.get("PATH", "")},
            )
            return {
                "status": "success" if result.returncode == 0 else "failed",
                "out": result.stdout,
                "err": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"status": "failed", "out": "", "err": "Execution timed out"}
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _run_docker(self, code: str, timeout: int) -> Dict[str, str]:
        workdir = Path(tempfile.mkdtemp(prefix="ai_ceo_exec_"))
        script = workdir / "task.py"
        script.write_text(code)
        container = None
        try:
            container = self.client.containers.run(
                self.image,
                command=["python", "/workspace/task.py"],
                volumes={str(workdir): {"bind": "/workspace", "mode": "ro"}},
                working_dir="/workspace",
                detach=True,
                network_disabled=True,
                mem_limit="256m",
                nano_cpus=1_000_000_000,
                pids_limit=64,
                security_opt=["no-new-privileges"],
                read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                stderr=True,
                stdout=True,
                auto_remove=False,
            )
            start = time.time()
            while time.time() - start < timeout:
                container.reload()
                if container.status in {"exited", "dead"}:
                    break
                time.sleep(0.2)
            else:
                container.kill()
                return {"status": "failed", "out": "", "err": "Execution timed out"}

            result = container.wait()
            logs = container.logs(stdout=True, stderr=False).decode(errors="ignore")
            err = container.logs(stdout=False, stderr=True).decode(errors="ignore")
            code = int(result.get("StatusCode", 1))
            return {"status": "success" if code == 0 else "failed", "out": logs, "err": err}
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            shutil.rmtree(workdir, ignore_errors=True)
