"""Tests de la meta-evolución acotada (F1/F2) y del presupuesto (F4/F5):
acceptance gate con train/dev, componentes del harness, coste real y hard stop
por estancamiento."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.budget_tracker import BudgetTracker
from agent.llm import LLM
from agent.memory_db import MemoryDB
from config import PATHS
from tools.domain.meta_editor import EditSkill, ReviewHarness, resolve_component


def test_resolve_component_maps_domain_paths():
    assert resolve_component("generated/skills.yaml") == "context_memory"
    assert resolve_component("archetypes/landing-page/rules.yaml") == "tools_specs"
    assert resolve_component("otro/archivo.yaml") is None


def test_edit_skill_proposes_not_applies(tmp_path):
    """F1: edit_skill registra pending y deja staging, NO toca domain/ vivo."""
    file = "generated/test-gate-tmp.yaml"
    target = PATHS["domain"] / file
    target.write_text("contenido: original\n")
    tool = EditSkill()
    res = tool.run(
        component="context_memory",
        path=file,
        instruction='{"nueva": ["seccion"]}',
        mode="replace",
        run_id="t-gate-prop",
    )
    assert "propuesta" in res and "pending" in res
    # domain/ vivo no cambió
    assert target.read_text() == "contenido: original\n"
    # la propuesta quedó registrada como pending
    db = MemoryDB()
    edits = db.harness_edits(decision="pending", run_id="t-gate-prop")
    assert edits, "debe existir propuesta pending"
    e = edits[0]
    assert e["component"] == "context_memory"
    assert e["file"] == file
    assert e["before"] == "contenido: original\n"
    # staging existe en domain/.proposals
    staged = PATHS["domain"] / ".proposals" / e["id"] / file
    assert staged.exists()
    db.conn.execute("DELETE FROM harness_edits WHERE run_id='t-gate-prop'")
    db.conn.commit()
    db.close()
    target.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(PATHS["domain"] / ".proposals", ignore_errors=True)


def test_edit_skill_rejects_wrong_component():
    tool = EditSkill()
    res = tool.run(
        component="context_memory",
        path="archetypes/landing-page/rules.yaml",
        instruction='{"a": "b"}',
        mode="replace",
    )
    assert "ERROR" in res and "no coincide" in res


def test_edit_skill_rejects_unknown_component_path():
    tool = EditSkill()
    res = tool.run(
        component="context_memory",
        path="fuera/archivo.yaml",
        instruction='{"a": "b"}',
        mode="replace",
    )
    assert "ERROR" in res and "no pertenece" in res


def test_edit_skill_validates_yaml():
    tool = EditSkill()
    res = tool.run(
        component="context_memory",
        path="generated/skills.yaml",
        instruction="esto no es yaml: [{{",
        mode="replace",
    )
    assert "ERROR" in res


def test_review_harness_groups_by_component():
    out = ReviewHarness().run()
    assert "[context_memory]" in out
    assert "[tools_specs]" in out
    assert ".proposals" not in out


TMP_FILE = "generated/test-gate-tmp.yaml"


def _tmp_target() -> Path:
    return PATHS["domain"] / TMP_FILE


def test_gate_accepts_when_train_up_and_dev_ok(monkeypatch, tmp_path):
    """F1: el acceptance gate acepta si train mejora y dev no degrada."""
    from scripts import gate_harness_edit as g

    _tmp_target().write_text("antes")
    calls = {"n": 0}

    def fake_J(arq, task, turns, target_h):
        calls["n"] += 1
        if calls["n"] in (1, 2):
            return 50.0  # baseline train/dev
        if calls["n"] in (3, 4):
            return 60.0  # after: train mejora, dev igual
        return 60.0

    monkeypatch.setattr(g, "_short_run_score", fake_J)
    edit = {
        "id": "p-gate-ok",
        "file": TMP_FILE,
        "component": "context_memory",
        "before": "antes",
        "after": "nuevo",
    }
    try:
        r = g.gate_proposal(edit, "landing-page", "T1", "ecommerce", "T2",
                            turns=3, target_h=1, dry_run=False)
        assert r["decision"] == "accepted"
        # como es accepted, el archivo quedó con `after`
        assert _tmp_target().read_text() == "nuevo"
    finally:
        _tmp_target().unlink(missing_ok=True)


def test_gate_rejects_when_train_not_improve(monkeypatch, tmp_path):
    """F1: sin mejora en train se rechaza y se hace rollback a `before`."""
    from scripts import gate_harness_edit as g

    _tmp_target().write_text("ORIGINAL")
    calls = {"n": 0}

    def fake_J(arq, task, turns, target_h):
        calls["n"] += 1
        return 50.0  # sin mejora

    monkeypatch.setattr(g, "_short_run_score", fake_J)
    edit = {
        "id": "p-gate-rej",
        "file": TMP_FILE,
        "component": "context_memory",
        "before": "ORIGINAL",
        "after": "CON_EDIT",
    }
    try:
        r = g.gate_proposal(edit, "landing-page", "T1", "ecommerce", "T2",
                            turns=3, target_h=1, dry_run=False)
        assert r["decision"] == "rejected"
        # rollback: el archivo vuelve a `before`
        assert _tmp_target().read_text() == "ORIGINAL"
    finally:
        _tmp_target().unlink(missing_ok=True)


def test_gate_rejects_when_dev_degrades(monkeypatch, tmp_path):
    """F1: aunque train mejore, si dev degrada se rechaza."""
    from scripts import gate_harness_edit as g

    _tmp_target().write_text("ORIGINAL")
    seq = {"n": 0}

    def fake_J(arq, task, turns, target_h):
        seq["n"] += 1
        # 1: train before 50, 2: dev before 50, 3: train after 70, 4: dev after 40
        return (50, 50, 70, 40)[seq["n"] - 1]

    monkeypatch.setattr(g, "_short_run_score", fake_J)
    edit = {
        "id": "p-gate-dev",
        "file": TMP_FILE,
        "component": "context_memory",
        "before": "ORIGINAL",
        "after": "CON_EDIT",
    }
    try:
        r = g.gate_proposal(edit, "landing-page", "T1", "ecommerce", "T2",
                            turns=3, target_h=1, dry_run=False)
        assert r["decision"] == "rejected"
        assert "dev degrada" in r["reason"]
        assert _tmp_target().read_text() == "ORIGINAL"
    finally:
        _tmp_target().unlink(missing_ok=True)


def test_gate_persists_decision_in_db(monkeypatch, tmp_path):
    """F1: gate_proposal persiste la decisión en harness_edits."""
    from scripts import gate_harness_edit as g

    _tmp_target().write_text("b")
    db = MemoryDB()
    db.conn.execute("DELETE FROM harness_edits WHERE id='p-persist'")
    db.conn.commit()
    db.add_harness_edit("p-persist", "t-persist", "context_memory",
                        TMP_FILE, "b", "a", "replace", "plan")
    edit = db.get_harness_edit("p-persist")
    db.close()

    monkeypatch.setattr(g, "_short_run_score", lambda *a, **k: 50.0)
    try:
        g.gate_proposal(edit, "landing-page", "T1", "ecommerce", "T2",
                        turns=3, target_h=1, dry_run=False)
        db2 = MemoryDB()
        e2 = db2.get_harness_edit("p-persist")
        assert e2["decision"] == "rejected"
        db2.conn.execute("DELETE FROM harness_edits WHERE id='p-persist'")
        db2.conn.commit()
        db2.close()
        assert _tmp_target().read_text() == "b"  # rollback
    finally:
        _tmp_target().unlink(missing_ok=True)


def test_budget_stagnation_is_hard_stop():
    """F5: el estancamiento por stagnación es un hard stop real en done()."""
    b = BudgetTracker(max_turns=20, stagnation_hard_stop=3, min_improvement_percent=2.0)
    b.start()
    # 4 turnos: el 1º establece best (flat=0), luego 3 flat -> hard stop
    for _ in range(4):
        b.register_evaluation(50.0)
    reason = b.done()
    assert reason and "stagnación" in reason.lower()


def test_budget_stagnation_resets_on_improvement():
    b = BudgetTracker(max_turns=20, stagnation_hard_stop=3, min_improvement_percent=2.0)
    b.start()
    b.register_evaluation(50.0)
    b.register_evaluation(50.0)
    b.register_evaluation(52.0)  # mejora >2% respecto a best
    assert b.flat_turns == 0
    assert b.done() is None


def test_budget_cost_real_tracking():
    """F4: el presupuesto refleja el coste estimado del LLM."""
    b = BudgetTracker(max_turns=20, max_cost_usd=0.001)
    b.start()
    b.add_turn_cost(0.002)
    assert b.done() and "coste" in b.done().lower()


def test_llm_estimate_cost():
    """F4: LLM.estimate_cost calcula USD según MODEL_PRICES (default si modelo desconocido)."""
    c = LLM.estimate_cost(1_000_000, 0, "gemini-3.1-flash-lite")
    assert c == 0.10
    c2 = LLM.estimate_cost(1_000_000, 0, "modelo-desconocido")
    assert c2 == 1.25


class _FakeLLM:
    model = "fake"


def _seed_agent(tmp_path, task="grafo de repos", archetype="knowledge-graph"):
    from agent.agent import Agent

    run_dir = tmp_path / "runs" / "seed-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    agent = Agent(_FakeLLM(), archetype_name=archetype, task=task,
                  run_dir=run_dir, verbose=False, max_turns=5)
    agent.db = None
    agent.tree.db = None
    agent.tree.path = run_dir / "search_tree.json"
    agent.tree.nodes = {}
    return agent, run_dir


def test_seed_from_workspace_registers_h0(tmp_path, monkeypatch):
    """PERSISTENCIA: si workspace/current tiene candidato al arrancar, se registra
    como H0 baseline (no se regenera desde cero)."""
    wc = PATHS["current"]
    wc.mkdir(parents=True, exist_ok=True)
    (wc / "index.html").write_text(
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Semilla</title></head><body><h1>Grafo</h1>"
        "<section class='graph-container'></section></body></html>"
    )
    (wc / "styles.css").write_text("body{color:red}")
    (wc / "app.js").write_text("const svg=document.getElementById('graph');")

    agent, run_dir = _seed_agent(tmp_path)
    try:
        agent._seed_from_workspace()
        assert "H0" in agent.tree.nodes
        n = agent.tree.nodes["H0"]
        assert n.action == "seed_workspace"
        assert n.metrics.get("total") is not None
        assert agent.hypothesis_count == 1
        assert agent.seeded is True
        assert (run_dir / "candidates" / "H0" / "index.html").exists()
    finally:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
        # IMPORTANTE: no dejar el candidato de prueba en el workspace REAL, o el
        # siguiente arranque del agente lo tomará como semilla (persistencia).
        for f in ("index.html", "styles.css", "app.js"):
            (wc / f).unlink(missing_ok=True)


def test_seed_from_workspace_noop_without_candidate(tmp_path):
    """Sin candidato previo en workspace, no se crea H0."""
    wc = PATHS["current"]
    wc.mkdir(parents=True, exist_ok=True)
    had = (wc / "index.html").exists()
    idx = wc / "index.html"
    if had:
        idx.rename(wc / "index.html.bak")

    agent, run_dir = _seed_agent(tmp_path, archetype="landing-page", task="landing")
    try:
        agent._seed_from_workspace()
        assert agent.tree.nodes == {}
        assert agent.hypothesis_count == 0
        assert not hasattr(agent, "seeded")
    finally:
        if had:
            (wc / "index.html.bak").rename(wc / "index.html")
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))