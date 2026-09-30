"""Test de que una run que muere queda registrada como 'interrupted'.

Contexto: la battery de knowledge-graph del 2026-09-29 murió por
`RuntimeError: Todos los modelos fallaron: 503 UNAVAILABLE`. Como `Agent.run()`
no tenía try/except, la run quedaba en `status='running'` para siempre en
memory.db. En la base ya había 55 runs colgadas así: el registro mentía sobre
qué runs terminaron.

Este test fija que ante cualquier excepción (incluida KeyboardInterrupt) la
run se marca 'interrupted' con la causa y la DB se cierra, y que la excepción
se propaga (no se traga silenciosamente).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.agent import Agent
from agent.memory_db import MemoryDB


class _BoomLLM:
    model = "fake"
    cost_so_far = 0.0
    last_usage = (0, 0)

    def generate(self, *a, **k):
        raise RuntimeError("Todos los modelos fallaron: 503 UNAVAILABLE high demand")


class _Reg:
    def get(self, name):
        raise KeyError(name)


def _agent(tmp_path, db):
    ag = Agent.__new__(Agent)  # bypass de __init__: no queremos la run completa
    ag.run_id = "run-interrupt-test"
    ag.db = db
    ag.budget = type("B", (), {"start": lambda s: None})()
    ag.turn = 0
    return ag


def test_run_marks_interrupted_on_crash(tmp_path, monkeypatch):
    db = MemoryDB(path=tmp_path / "mem.db")
    db.upsert_run(run_id="run-interrupt-test", status="running")
    ag = _agent(tmp_path, db)
    monkeypatch.setattr(Agent, "_log", lambda self, *a, **k: None)

    def boom(self, registry, initial_url=""):
        raise RuntimeError("503 UNAVAILABLE high demand")

    monkeypatch.setattr(Agent, "_run_inner", boom)

    with pytest.raises(RuntimeError, match="503 UNAVAILABLE"):
        ag.run(_Reg())

    # run() cierra la DB al morirse: reabrimos para comprobar el estado.
    db2 = MemoryDB(path=tmp_path / "mem.db")
    row = db2.conn.execute(
        "SELECT status, harness_diff FROM runs WHERE id='run-interrupt-test'"
    ).fetchone()
    assert row[0] == "interrupted", f"debe quedar interrupted, no {row[0]}"
    assert "503 UNAVAILABLE" in (row[1] or ""), "debe guardar la causa"


def test_run_marks_interrupted_on_keyboard_interrupt(tmp_path, monkeypatch):
    """Un Ctrl-C también debe cerrar la run limpiamente."""
    db = MemoryDB(path=tmp_path / "mem.db")
    db.upsert_run(run_id="run-interrupt-test", status="running")
    ag = _agent(tmp_path, db)
    monkeypatch.setattr(Agent, "_log", lambda self, *a, **k: None)

    def boom(self, registry, initial_url=""):
        raise KeyboardInterrupt

    monkeypatch.setattr(Agent, "_run_inner", boom)

    with pytest.raises(KeyboardInterrupt):
        ag.run(_Reg())

    db2 = MemoryDB(path=tmp_path / "mem.db")
    status = db2.conn.execute(
        "SELECT status FROM runs WHERE id='run-interrupt-test'"
    ).fetchone()[0]
    assert status == "interrupted"


def test_successful_run_still_reports_done(tmp_path, monkeypatch):
    """Sanidad: el wrapper no debe alterar una run que termina bien."""
    db = MemoryDB(path=tmp_path / "mem.db")
    db.upsert_run(run_id="run-interrupt-test", status="running")
    ag = _agent(tmp_path, db)
    monkeypatch.setattr(Agent, "_log", lambda self, *a, **k: None)
    monkeypatch.setattr(Agent, "_run_inner", lambda self, r, u="": "FINAL_OK")
    assert ag.run(_Reg()) == "FINAL_OK"
    status = db.conn.execute(
        "SELECT status FROM runs WHERE id='run-interrupt-test'"
    ).fetchone()[0]
    assert status == "running"  # el _run_inner real es quien pone 'done'


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
