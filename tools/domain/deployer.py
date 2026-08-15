"""Herramientas de dominio adicionales: deploy_preview (servidor estático local)
y git_ops (snapshot por candidato)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from config import PATHS
from tools.base import Tool


class DeployPreview(Tool):
    name = "deploy_preview"
    description = "Levanta o informa cómo levantar un preview local del candidato (http.server estático)."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "port": {"type": "integer", "description": "Puerto para el preview"},
                },
            },
        }

    def run(self, port: int = 8800, **kwargs) -> str:
        target = PATHS["current"]
        if not (target / "index.html").exists():
            return "ERROR: no hay index.html en workspace/current"
        return (
            f"Para ver el preview ejecuta:\n"
            f"  cd {target} && python3 -m http.server {port}\n"
            f"y abre http://localhost:{port}"
        )


class GitSnapshot(Tool):
    name = "git_snapshot"
    description = "Crea un snapshot versionado (git) del candidato actual dentro de runs/."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["candidate_id", "message"],
            },
        }

    def run(self, candidate_id: str = "", message: str = "", **kwargs) -> str:
        src = PATHS["current"]
        if not (src / "index.html").exists():
            return "ERROR: no hay candidato actual"
        dest = PATHS["runs"] / kwargs.get("run_id", "latest") / "candidates" / candidate_id
        dest.mkdir(parents=True, exist_ok=True)
        import shutil

        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
        return f"OK: candidato {candidate_id} guardado en {dest} ({message})"