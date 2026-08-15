"""Ejecución de código Python y Bash en sandbox (con blocklist para bash)."""
from __future__ import annotations

import io
import subprocess
import sys
import traceback
from contextlib import redirect_stdout

from tools.base import Tool

BLOCKED_PATTERNS = [
    "rm -rf",
    "rm -fr",
    "chmod 777",
    "mkfs",
    ":(){",
    "> /dev/sda",
    "sudo ",
    "--no-preserve-root",
]


class PythonExec(Tool):
    name = "python_exec"
    description = (
        "Ejecuta código Python en un sandbox (timeout 120s). La salida es la salida "
        "estándar del script. Útil para analizar métricas, estructuras o lógica."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Código Python a ejecutar"},
                },
                "required": ["code"],
            },
        }

    def run(self, code: str = "", **kwargs) -> str:
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(code, {"__name__": "__main__"}, {})
            out = buf.getvalue()
            return f"SALIDA:\n{out[:6000]}" if out else "OK: sin salida"
        except Exception:
            return f"SALIDA:\n{buf.getvalue()[:3000]}\nERROR:\n{traceback.format_exc()[:3000]}"


class BashExec(Tool):
    name = "bash"
    description = "Ejecuta un comando bash (con timeout y blocklist de seguridad)."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        }

    def run(self, command: str = "", **kwargs) -> str:
        low = command.lower()
        for pat in BLOCKED_PATTERNS:
            if pat in low:
                return f"ERROR: comando bloqueado (contiene {pat!r})"
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                executable="/bin/bash",
            )
            out = result.stdout[:6000]
            err = result.stderr[:3000]
            rc = result.returncode
            return f"exit={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}" if err else f"exit={rc}\n{out}"
        except subprocess.TimeoutExpired:
            return "ERROR: timeout 120s"
        except Exception as e:
            return f"ERROR: {e}"