"""Tests del sandbox de file_io (rutas con prefijos workspace/runs/memory/domain).

Bug corregido: _resolve duplicaba la ruta (workspace/current -> workspace/current/
workspace/current) porque solo manejaba 'domain/' y 'harness/'. Ahora todos los
prefijos de ALLOWED_ROOTS se resuelven contra su raíz correspondiente.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PATHS
from tools.file_io import _resolve


def test_resolve_defaults_to_current():
    p = _resolve("index.html")
    assert p == PATHS["current"] / "index.html"


def test_resolve_workspace_prefix():
    p = _resolve("workspace/current")
    assert p == PATHS["current"], p
    p2 = _resolve("workspace/temp")
    assert p2 == PATHS["workspace"] / "temp"


def test_resolve_runs_prefix():
    p = _resolve("runs/20260101T000000--x")
    assert p == PATHS["runs"] / "20260101T000000--x", p
    assert not str(p).startswith(str(PATHS["runs"] / "runs")), "ruta duplicada"


def test_resolve_memory_prefix():
    p = _resolve("memory/lessons.db")
    assert p == PATHS["memory"] / "lessons.db", p


def test_resolve_domain_prefix():
    p = _resolve("domain/archetypes/x/rules.yaml")
    assert p == PATHS["domain"] / "archetypes" / "x" / "rules.yaml", p


def test_resolve_templates_prefix():
    p = _resolve("templates/index.html")
    assert p == PATHS["templates"] / "index.html", p


def test_resolve_root_shorthand():
    assert _resolve(".") == PATHS["root"]
    assert _resolve("harness") == PATHS["root"]
    assert _resolve("workspace") == PATHS["workspace"]
    assert _resolve("runs") == PATHS["runs"]
    assert _resolve("memory") == PATHS["memory"]


def test_resolve_outside_sandbox_raises():
    import pytest as _pt
    with _pt.raises(PermissionError):
        _resolve("/etc/passwd")
    # ruta absoluta a un dir fuera del sandbox (p. ej. home)
    with _pt.raises(PermissionError):
        _resolve(str(Path.home()))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))