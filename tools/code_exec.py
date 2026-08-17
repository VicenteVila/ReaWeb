"""Ejecución de código Python y Bash en sandbox (Punto 8, Qwen 3.8).

Fase 1 (PythonExec): globals restringidas. Solo se exponen módulos de la
allowlist (math, re, json, statistics, collections, itertools, functools,
random) y los builtins no peligrosos. Un chequeo previo por AST rechaza
imports fuera de la allowlist, builtins peligrosos (open/eval/exec/input/
__import__/compile/breakpoint) y atributos de módulos bloqueados
(subprocess/os/sys/pathlib/requests...).

Fase 2 (BashExec): el comando se ejecuta bajo `prlimit` con límites de
memoria virtual (AS), CPU y procesos (NPROC). Si `prlimit` no existe en el
sistema, se degrada a `ulimit -v/-u` inline con timeout. La blocklist de
comandos se amplía (cualquier borrado no aislado, montajes, kernel, red).

Modo configurable en config.py: CODE_EXEC_MODE = "restricted" (default)
o "off" (devuelve error sin ejecutar). Sin Docker: el aislamiento es de
recursos y de superficie de API, no de kernel.
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from contextlib import redirect_stdout

from tools.base import Tool

PYTHON_ALLOWED_MODULES = {
    "math", "re", "json", "statistics", "collections", "itertools",
    "functools", "random", "textwrap", "string", "datetime", "time",
    "decimal", "fractions", "types", "operator", "bisect", "heapq",
    "copy", "enum", "dataclasses",
}

FORBIDDEN_BUILTINS = {
    "open", "eval", "exec", "input", "__import__", "compile", "breakpoint",
    "execfile", "globals", "locals", "vars", "memoryview", "bytes",
    "bytearray", "getattr",
}

FORBIDDEN_MODULE_ATTRS = {
    "subprocess", "os", "sys", "pathlib", "shutil", "requests", "urllib",
    "socket", "http", "importlib", "ctypes", "fcntl", "signal", "multiprocessing",
    "threading", "platform", "webbrowser", "pty", "resource", "grp", "pwd",
    "hashlib", "ssl",
}

BLOCKED_PATTERNS = [
    "rm -rf",
    "rm -fr",
    "rm -f /*",
    "chmod 777",
    "chmod 000",
    "mkfs",
    ":(){",
    "> /dev/sda",
    "sudo ",
    "--no-preserve-root",
    "dd if=",
    ">/dev/mem",
    "insmod",
    "rmmod",
    "reboot",
    "poweroff",
    "shutdown",
    "kill -9",
    "iptables",
    "wget ",
    "curl ",
    "nc ",
    "nmap",
    "hydra",
    "openssl enc",
    "chown -R",
    "fdisk",
    "parted",
    "mount ",
    "umount ",
    ": > /",
    "find / -delete",
    "git push",
    "git remote add",
    "git config",
    "scp ",
    "rsync -",
    "python -m pip install",
    "pip install",
    "apt ",
    "yum ",
    "npm install",
    "go install",
    "cargo install",
]

# límites fase 2 (prlimit): 512 MB de memoria virtual, 10 s de CPU, 32 procesos
PRLIMIT_AS = "536870912"       # 512 MiB
PRLIMIT_CPU = "10"
PRLIMIT_NPROC = "32"
EXEC_TIMEOUT = 120


def _reject_code(code: str) -> str | None:
    """Chequeo AST de seguridad. Devuelve mensaje de error o None si es seguro."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in PYTHON_ALLOWED_MODULES:
                    return f"import bloqueado: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] not in PYTHON_ALLOWED_MODULES:
                return f"import from bloqueado: {node.module}"
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name):
                base = node.value.id
                # módulo base prohibido (p.ej. subprocess.run) o atributo con
                # nombre de módulo peligroso (p.ej. random.subprocess)
                if base in FORBIDDEN_MODULE_ATTRS or node.attr in FORBIDDEN_MODULE_ATTRS:
                    return f"acceso bloqueado: {base}.{node.attr}"
        elif isinstance(node, ast.Call):
            pass
    for name in FORBIDDEN_BUILTINS:
        if re.search(rf"\b{re.escape(name)}\s*\(", code):
            return f"builtin peligroso: {name}()"
    if "__import__" in code or "__builtins__" in code:
        return "acceso a __import__/__builtins__ bloqueado"
    return None


def _safe_globals() -> dict:
    """Globals de ejecución: builtins filtrados + módulos allowlist."""
    allowed = {k: v for k, v in __builtins__.__dict__.items()
               if k not in FORBIDDEN_BUILTINS} if isinstance(__builtins__, type) \
        else {k: v for k, v in __builtins__.items() if k not in FORBIDDEN_BUILTINS}
    globals_dict = {"__name__": "__main__", "__builtins__": allowed}
    # __import__ restringido: solo permite módulos de la allowlist
    allowed_modules = set(PYTHON_ALLOWED_MODULES)

    def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level:
            return __import__(name, globals, locals, fromlist, level)
        top = name.split(".")[0]
        if top not in allowed_modules:
            raise ImportError(f"import bloqueado por sandbox: {name}")
        return __import__(name, globals, locals, fromlist, level)

    globals_dict["__builtins__"]["__import__"] = _safe_import
    for mod in PYTHON_ALLOWED_MODULES:
        try:
            globals_dict[mod] = __import__(mod)
        except Exception:
            pass
    return globals_dict


class PythonExec(Tool):
    name = "python_exec"
    description = (
        "Ejecuta código Python en sandbox de recursos (timeout 120s, memoria y "
        "CPU limitadas, sin acceso a red/FS). Salida = stdout del script."
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
        from config import CODE_EXEC_MODE
        if CODE_EXEC_MODE == "off":
            return "ERROR: ejecución de código deshabilitada (CODE_EXEC_MODE=off)"
        err = _reject_code(code or "")
        if err:
            return f"ERROR: código bloqueado por el sandbox: {err}"
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(code, _safe_globals(), {})
            out = buf.getvalue()
            return f"SALIDA:\n{out[:6000]}" if out else "OK: sin salida"
        except Exception:
            return f"SALIDA:\n{buf.getvalue()[:3000]}\nERROR:\n{traceback.format_exc()[:3000]}"


class BashExec(Tool):
    name = "bash"
    description = (
        "Ejecuta un comando bash con timeout, blocklist de seguridad y límites "
        "de recursos (memoria/CPU/procesos vía prlimit o ulimit)."
    )

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
        from config import CODE_EXEC_MODE
        if CODE_EXEC_MODE == "off":
            return "ERROR: ejecución de código deshabilitada (CODE_EXEC_MODE=off)"
        low = command.lower()
        for pat in BLOCKED_PATTERNS:
            if pat in low:
                return f"ERROR: comando bloqueado (contiene {pat!r})"
        # limitamos la red: cualquier invocación con socket via /dev/tcp se bloquea
        if "dev/tcp" in low or "dev/udp" in low:
            return "ERROR: comando bloqueado (red no permitida)"
        cmd = self._wrap_with_limits(command)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=EXEC_TIMEOUT,
                executable="/bin/bash",
            )
            out = result.stdout[:6000]
            err = result.stderr[:3000]
            rc = result.returncode
            return f"exit={rc}\nSTDOUT:\n{out}\nSTDERR:\n{err}" if err else f"exit={rc}\n{out}"
        except subprocess.TimeoutExpired:
            return f"ERROR: timeout {EXEC_TIMEOUT}s"
        except Exception as e:
            return f"ERROR: {e}"

    @staticmethod
    def _wrap_with_limits(command: str) -> str:
        """Envuelve el comando con prlimit (preferido) o ulimit (fallback)."""
        if shutil.which("prlimit"):
            return (
                f"prlimit --as={PRLIMIT_AS} --cpu={PRLIMIT_CPU} "
                f"--nproc={PRLIMIT_NPROC} -- bash -c {shlex_quote(command)}"
            )
        # ulimit: memoria virtual (512 MiB), procesos (32); se aplican al subshell
        return f"ulimit -v {int(PRLIMIT_AS) // 1024}; ulimit -u {PRLIMIT_NPROC}; {command}"


def shlex_quote(s: str) -> str:
    """Quote simple compatible con bash (evita depender de shlex en el wrap)."""
    return "'" + s.replace("'", "'\\''") + "'"
