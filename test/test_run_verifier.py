"""Test del Verificador L0 + Preflight L3.

L0: tras generate_candidate se comprueban invariantes LOCALES y gratis; si
fallan, el harness restaura el workspace desde la última snapshot verificada,
retira el nodo del árbol (memoria y DB) y realimenta al agente. Rechazos en
cadena escalan una vez (auto_unblock) y después detienen la run honestamente.

Ninguno de estos tests hace llamadas al LLM: se simulan respuestas o se
comprueba la lógica local (misión del verificador: cero consumo de cuota).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agent.agent import Agent
from agent.memory_db import MemoryDB
from agent.state import SearchTree, TreeNode


@pytest.fixture
def patched_paths(tmp_path, monkeypatch):
    """Apuntar PATHS['current'] y PATHS['runs'] a directorios temporales.
    El dict PATHS es compartido entre agent.py y web_generator.py (import de
    config), así que una sola modificación vale para ambos."""
    runs = tmp_path / "runs"
    cur = tmp_path / "workspace" / "current"
    runs.mkdir(parents=True, exist_ok=True)
    cur.mkdir(parents=True, exist_ok=True)
    monkeypatch.setitem(config.PATHS, "runs", runs)
    monkeypatch.setitem(config.PATHS, "current", cur)
    monkeypatch.setattr(config, "VERIFIER_CHECK_RENDER", False)
    return {"runs": runs, "current": cur}


def _mk_agent(tmp_path, monkeypatch, patched_paths):
    db = MemoryDB(path=tmp_path / "mem.db")
    ag = Agent.__new__(Agent)  # bypass de __init__ completo
    ag.run_id = "run-verify"
    ag.db = db
    ag.tree = SearchTree(path=tmp_path / "search_tree.json", run_id="run-verify",
                         db=db)
    ag.history = []
    ag._reject_streak = 0
    ag._reject_escalated_once = False
    ag.logged = []
    monkeypatch.setattr(Agent, "_log", lambda self, *a, **k: self.logged.append(a))
    return ag


def _node(nid, total, functional=None):
    metrics = {"total": total}
    if functional is not None:
        metrics["functional"] = functional
    return TreeNode(id=nid, parent="H0", action="generate_candidate",
                    metrics=metrics, status="best_branch")


# --- _verify_candidate -------------------------------------------------

def test_verify_rejects_missing_index(patched_paths, monkeypatch, tmp_path):
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    ag.tree.add(_node("H1", 90))
    reason = ag._verify_candidate("H1", prev_node=None)
    assert "no se generó index.html" in reason


def test_verify_accepts_clean_page(patched_paths, monkeypatch, tmp_path):
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    (patched_paths["current"] / "index.html").write_text("<html><body>ok</body></html>")
    ag.tree.add(_node("H1", 88, functional=90))
    prev = _node("H0", 80, functional=85)
    assert ag._verify_candidate("H1", prev_node=prev) == ""


def test_verify_rejects_functional_regression(patched_paths, monkeypatch, tmp_path):
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    (patched_paths["current"] / "index.html").write_text("<html><body>ok</body></html>")
    ag.tree.add(_node("H1", 85, functional=30))  # pasó a romper lo que iba bien
    prev = _node("H0", 80, functional=85)        # previo con funcional >= gate
    reason = ag._verify_candidate("H1", prev_node=prev)
    assert "rompió la funcionalidad previa" in reason


def test_verify_ignores_simple_score_regression(patched_paths, monkeypatch, tmp_path):
    """Una regresión legítima de score NO es rechazo: es señal de exploración."""
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    (patched_paths["current"] / "index.html").write_text("<html><body>ok</body></html>")
    ag.tree.add(_node("H1", 72, functional=90))
    prev = _node("H0", 85, functional=90)
    assert ag._verify_candidate("H1", prev_node=prev) == ""


# --- _reject_candidate: rollback workspace + árbol ----------------------

def test_reject_restores_workspace_and_removes_node(patched_paths, monkeypatch,
                                                    tmp_path):
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    runs = patched_paths["runs"]
    cur = patched_paths["current"]

    snap = runs / "run-verify" / "candidates" / "H0"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "index.html").write_text("<html>Bueno</html>")
    (snap / "styles.css").write_text("body{}")

    (cur / "index.html").write_text("<html>ROTO</html>")
    (cur / "assets.js").write_text("window.broken=")

    prev = _node("H0", 95, functional=95)
    ag.tree.add(prev)                       # H0 bueno (snapshot congelado)
    ag.tree.add(_node("H1", 90, functional=20))  # el candidato roto

    ag._reject_candidate("H1", "rompió la funcionalidad previa: 95 -> 20",
                         registry=None, prev_node=prev)

    # workspace restaurado byte a byte desde H0
    assert (cur / "index.html").read_text() == "<html>Bueno</html>"
    assert (cur / "styles.css").read_text() == "body{}"
    assert not (cur / "assets.js").exists()

    # nodo retirado del árbol: memoria, json y DB
    assert "H1" not in ag.tree.nodes
    saved = json.loads((tmp_path / "search_tree.json").read_text())
    assert "H1" not in saved["nodes"]
    assert [n["node_id"] for n in ag.db.nodes("run-verify")] == ["H0"]

    # feedback inyectado para que el agente reintente desde el estado bueno
    feedback = [m for m in ag.history if m["role"] == "user" and "DESCARTÓ" in m["parts"][0]["text"]]
    assert feedback, "debe inyectar feedback de descarte"
    assert "H0" in feedback[0]["parts"][0]["text"]

    # rastro auditable en el transcript
    evts = [a for a in ag.logged if a[0] == "system"]
    assert any("step_rejected" in (a[1].get("event", "") if len(a) > 1 and isinstance(a[1], dict) else "")
               for a in evts)


def test_reject_without_prev_just_removes_node(patched_paths, monkeypatch, tmp_path):
    # primer candidato H0 roto: no hay snapshot previo; solo se retira el nodo
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    ag.tree.add(_node("H0", 80, functional=10))
    ag._reject_candidate("H0", "la página no renderiza en Chrome",
                         registry=None, prev_node=None)
    assert "H0" not in ag.tree.nodes
    assert ag._reject_streak == 1


def test_accepted_candidate_resets_reject_streak(patched_paths, monkeypatch, tmp_path):
    # los rechazos deben ser CONSECUTIVOS: aceptar un paso resetea la racha y
    # evita cierre prematuro con patrón bueno-malo-bueno-malo
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    ag.tree.add(_node("H0", 95, functional=95))
    ag._reject_candidate("H0", "motivo", registry=None, prev_node=None)
    assert ag._reject_streak == 1

    cur = patched_paths["current"]
    (cur / "index.html").write_text("<html>OK</html>")
    assert ag._verify_candidate("H0", prev_node=None) == ""
    assert ag._reject_streak == 0, "aceptar tras un rechazo resetea la racha"


# --- escalada y cierre honesto ------------------------------------------

def test_escalates_once_via_auto_unblock(patched_paths, monkeypatch, tmp_path):
    ag = _mk_agent(tmp_path, monkeypatch, patched_paths)
    calls = []
    monkeypatch.setattr(Agent, "_auto_unblock", lambda self, reg: calls.append(1))
    monkeypatch.setattr(config, "VERIFIER_MAX_REJECT_BEFORE_ESCALATE", 2)
    for i in range(3):
        ag._reject_candidate(f"H{i}", "motivo", registry=None, prev_node=None)
    assert calls == [1], "escalada UNA sola vez, no en cada rechazo"


def test_stop_reason_threshold(monkeypatch, tmp_path):
    ag = Agent.__new__(Agent)
    ag._reject_streak = 0
    monkeypatch.setattr(config, "VERIFIER_MAX_REJECT_BEFORE_STOP", 3)
    assert ag._verifier_stop_reason() is None
    ag._reject_streak = 2
    assert ag._verifier_stop_reason() is None
    ag._reject_streak = 3
    assert ag._verifier_stop_reason() is not None


# --- Preflight L3 (sin llamadas reales) ---------------------------------

class _FakeResp:
    def __init__(self, text="OK", input_tokens=50, output_tokens=5):
        self.text = text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeLLMForPreflight:
    provider = "groq"
    model = "openai/gpt-oss-120b"
    _vision_models = None
    resp = None
    responses = []

    @staticmethod
    def _system_prompt():
        return "Eres un agente de diseño web senior."

    def generate(self, prompt, **kwargs):
        # la llamada del preflight nunca debe tocar un LLM real
        assert self.responses, "respuestas simuladas agotadas"
        return self.responses.pop(0)


class _FakeToolRegistry:
    def schemas(self):
        return [{"name": "generate_candidate", "parameters": {"type": "object", "properties": {}}}]


def test_preflight_fails_when_credentials_broken(monkeypatch, tmp_path, capsys):
    import agent.llm as llm_mod
    monkeypatch.setattr(config, "VISION_PROVIDER", "")

    class _Bad:
        provider = "gemini"
        model = "gemini-3.1-pro-preview"
        _vision_models = None

        def generate(self, prompt, **kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    monkeypatch.setattr(llm_mod, "LLM", lambda *a, **k: _Bad())
    from scripts.run_ab_pg_battery import preflight
    assert preflight("portfolio-creative", "Tarea", 6) == 2
    assert "PREFLIGHT_FAIL" in capsys.readouterr().out


def test_preflight_warns_on_413_like_prompt(monkeypatch, tmp_path, capsys):
    import agent.llm as llm_mod
    monkeypatch.setattr(config, "VISION_PROVIDER", "groq")
    _FakeLLMForPreflight.responses = [_FakeResp(text="OK", input_tokens=40),
                                      _FakeResp(text="x", input_tokens=7000, output_tokens=5)]
    monkeypatch.setattr(llm_mod, "LLM", lambda *a, **k: _FakeLLMForPreflight())
    from scripts.run_ab_pg_battery import preflight
    out = capsys.readouterr().out
    assert preflight("portfolio-creative", "Tarea", 6) == 2
    out = capsys.readouterr().out
    assert ">= 80% del limite" in out