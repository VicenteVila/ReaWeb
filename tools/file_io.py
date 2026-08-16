"""Tools de file I/O con sandbox restringido a workspace/ y runs/."""
from __future__ import annotations

import re
from pathlib import Path

from config import PATHS
from tools.base import Tool

ALLOWED_ROOTS = [PATHS["root"], PATHS["workspace"], PATHS["runs"], PATHS["memory"], PATHS["domain"], PATHS["templates"]]


def _resolve(path_str: str) -> Path:
    p = Path(path_str)
    if not p.is_absolute():
        s = str(p)
        if s.startswith("domain/"):
            p = PATHS["domain"] / s[len("domain/"):]
        elif s.startswith("harness/"):
            p = PATHS["root"] / s[len("harness/"):]
        elif s.startswith("workspace/"):
            p = PATHS["workspace"] / s[len("workspace/"):]
        elif s.startswith("runs/"):
            p = PATHS["runs"] / s[len("runs/"):]
        elif s.startswith("memory/"):
            p = PATHS["memory"] / s[len("memory/"):]
        elif s.startswith("templates/"):
            p = PATHS["templates"] / s[len("templates/"):]
        elif s in ("domain", "workspace", "runs", "memory", "templates"):
            p = PATHS[s]
        elif s in (".", "harness"):
            p = PATHS["root"]
        else:
            p = PATHS["current"] / p
    p = p.resolve()
    allowed = any(str(p).startswith(str(root.resolve())) for root in ALLOWED_ROOTS)
    if not allowed:
        raise PermissionError(f"Ruta fuera del sandbox: {p}")
    return p


class ReadFile(Tool):
    name = "read_file"
    description = "Lee el contenido de un archivo de texto."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa o absoluta del archivo"},
                },
                "required": ["path"],
            },
        }

    def run(self, path: str = "", **kwargs) -> str:
        p = _resolve(path)
        if not p.exists():
            return f"ERROR: no existe {p}"
        content = p.read_text(errors="replace")
        return f"{p}:\n{content[:8000]}"


class WriteFile(Tool):
    name = "write_file"
    description = "Crea o sobrescribe un archivo de texto."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        }

    def run(self, path: str = "", content: str = "", **kwargs) -> str:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"OK: escrito {len(content)} chars en {p}"


class EditFile(Tool):
    name = "edit_file"
    description = "Reemplaza una subcadena exacta por otra en un archivo."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        }

    def run(self, path: str = "", old: str = "", new: str = "", **kwargs) -> str:
        p = _resolve(path)
        if not p.exists():
            return f"ERROR: no existe {p}"
        content = p.read_text()
        if old not in content:
            return f"ERROR: el texto a reemplazar no se encontró en {p}"
        p.write_text(content.replace(old, new, 1))
        return f"OK: editado {p}"


class ListFiles(Tool):
    name = "list_files"
    description = "Lista archivos y directorios de una ruta (sandbox)."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta (por defecto workspace/current)"},
                },
            },
        }

    def run(self, path: str = "", **kwargs) -> str:
        base = PATHS["current"] if not path else _resolve(path)
        if not base.exists():
            return f"No existe {base}"
        entries = [f.name + ("/" if f.is_dir() else "") for f in sorted(base.iterdir())]
        return "\n".join(entries[:200]) or "(vacío)"