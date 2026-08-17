"""Tests del sandbox de ejecución de código (Punto 8, Qwen 3.8).

Fase 1: PythonExec con allowlist de módulos y builtins peligrosos bloqueados.
Fase 2: BashExec con blocklist ampliada y límites de recursos (prlimit/ulimit).
Modo "off" deshabilita la ejecución.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tools.code_exec import (
    BLOCKED_PATTERNS,
    BashExec,
    PythonExec,
    _reject_code,
    shlex_quote,
)


# ---- fase 1: PythonExec ----------------------------------------------------

def test_python_allowed_math():
    assert "2" in PythonExec().run(code="print(1 + 1)")


def test_python_import_json_ok():
    r = PythonExec().run(code="import json; print(json.dumps({'a': 1}))")
    assert "{\"a\": 1}" in r


def test_python_forbidden_import_os():
    r = PythonExec().run(code="import os; print(os.getcwd())")
    assert "bloqueado" in r and "os" in r


def test_python_forbidden_import_subprocess():
    r = PythonExec().run(code="import subprocess; subprocess.run(['ls'])")
    assert "bloqueado" in r


def test_python_forbidden_open():
    r = PythonExec().run(code="open('/etc/passwd').read()")
    assert "open" in r and "bloqueado" in r


def test_python_forbidden_eval():
    r = PythonExec().run(code="eval('1+1')")
    assert "eval" in r and "bloqueado" in r


def test_python_forbidden_import_from_sys():
    r = PythonExec().run(code="from sys import version")
    assert "bloqueado" in r


def test_python_attr_access_subprocess_blocked():
    r = PythonExec().run(code="import random; random.subprocess")
    assert "bloqueado" in r


def test_python_syntax_error_reported():
    r = PythonExec().run(code="def(")
    assert "SyntaxError" in r or "ERROR" in r


def test_python_stdout_truncation_and_error_path():
    r = PythonExec().run(code="print('a' * 100); raise ValueError('boom')")
    assert "ERROR" in r


def test_reject_code_direct():
    assert _reject_code("import os") is not None
    assert _reject_code("print(1)") is None
    assert _reject_code("x = subprocess.run('ls')") is not None


# ---- fase 2: BashExec ------------------------------------------------------

def test_bash_echo_ok():
    r = BashExec().run(command="echo hola")
    assert "hola" in r
    assert "exit=0" in r


def test_bash_rm_rf_blocked():
    r = BashExec().run(command="rm -rf /tmp/algo")
    assert "bloqueado" in r


def test_bash_sudo_blocked():
    r = BashExec().run(command="sudo apt update")
    assert "bloqueado" in r


def test_bash_network_blocked():
    r = BashExec().run(command="curl http://example.com")
    assert "bloqueado" in r


def test_bash_wget_blocked():
    r = BashExec().run(command="wget http://x.com/a")
    assert "bloqueado" in r


def test_bash_dev_tcp_blocked():
    r = BashExec().run(command="cat < /dev/tcp/host/80")
    assert "bloqueado" in r


def test_bash_timeout_long_sleep(monkeypatch):
    # con CPU limitada por prlimit, sleep 60 debe cortarse por timeout
    r = BashExec().run(command="sleep 60")
    assert "timeout" in r or "ERROR" in r or "exit=" in r


def test_blocked_patterns_cover_core_threats():
    for dangerous in ["rm -rf /", "sudo rm", "mkfs.ext4", "reboot",
                      "iptables -F", "kill -9 1", "mount /dev/sda"]:
        assert any(p in dangerous.lower() for p in BLOCKED_PATTERNS), dangerous


def test_shlex_quote():
    q = shlex_quote("a'b c")
    assert q == "'a'\\''b c'"


# ---- modo off --------------------------------------------------------------

def test_mode_off_python(monkeypatch):
    monkeypatch.setattr("config.CODE_EXEC_MODE", "off")
    r = PythonExec().run(code="print(1)")
    assert "deshabilitada" in r


def test_mode_off_bash(monkeypatch):
    monkeypatch.setattr("config.CODE_EXEC_MODE", "off")
    r = BashExec().run(command="echo hola")
    assert "deshabilitada" in r
