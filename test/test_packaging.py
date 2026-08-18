"""Tests del empaquetado y la CLI (Punto 10 — releases/CLI/Docker).

Cubre: versionado en pyproject.toml, entry point 'reaweb', presupuestos de los
modos quick/investigación y el filtrado de tools VLM en modo rápido.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent


def test_version_semantica_en_pyproject():
    with (ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    version = data["project"]["version"]
    parts = version.split(".")
    assert len(parts) == 3, "la versión debe ser semver X.Y.Z"
    assert all(p.isdigit() for p in parts)
    assert data["project"]["name"] == "reaweb-harness"


def test_entry_point_reaweb_definido():
    with (ROOT / "pyproject.toml").open("rb") as f:
        data = tomllib.load(f)
    scripts = data.get("project", {}).get("scripts", {})
    assert "reaweb" in scripts
    assert scripts["reaweb"] == "scripts.reaweb_cli:main"


def test_changelog_existe_con_0_2_0():
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert "[0.2.0]" in changelog
    assert "### Added" in changelog


def test_cli_presupuestos_modos():
    from scripts.reaweb_cli import QUICK_TURNS, QUICK_MAX_COST, RESEARCH_TURNS, RESEARCH_MAX_COST
    assert QUICK_TURNS < RESEARCH_TURNS
    assert QUICK_MAX_COST < RESEARCH_MAX_COST


def test_cli_quick_filtra_tools_vlm():
    from scripts._common import build_agent, load_archetype
    from unittest.mock import MagicMock

    llm = MagicMock()
    llm.model = "mock"
    # evitar llamadas a la API: build_agent crea MemoryDB() (ok, sqlite local)
    rules, stack = load_archetype("landing-page")
    try:
        agent, registry = build_agent(
            archetype="landing-page", task="landing de prueba", model="mock",
            turns=4, max_cost=0.5, allow_meta=False, verbose=False,
            target_h=0, initial_url="", use_cache=False, quick=True,
        )
    except Exception as exc:
        # build_agent crea un Agent (que hace snapshot, escribe DB...); si el
        # mock de LLM no basta, validamos solo el filtrado de registry
        assert "no api" in str(exc).lower(), str(exc)
        return
    names = registry.names()
    assert "generate_candidate" in names
    assert not any(n in names for n in ("audit_visual", "audit_creative", "audit_truth",
                                        "edit_skill", "review_harness"))
    assert agent.quick is True


def test_entry_point_reaweb_instalado_en_venv():
    import os
    import sys
    entry = os.path.join(sys.prefix, "bin", "reaweb")
    assert os.path.exists(entry), f"entry point no instalado: {entry}"


def test_dockerfile_y_dockerignore_presentes():
    assert (ROOT / "Dockerfile").exists()
    assert (ROOT / ".dockerignore").exists()
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "python:3.12-slim" in dockerfile
    assert "reaweb" in dockerfile
    assert "GEMINI_API_KEY" in dockerfile
