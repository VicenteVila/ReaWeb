"""Tests del Punto 12 (Graph Engineering): genealogía de ediciones (EvoFlow),
atribución causal (Who&When) y grafo de dependencias (Graph of Skills).

Referencia: Feng et al., "Graph Engineering in the Era of LLM Agents: From
Individual Intelligence to System Intelligence" — adaptado a un harness de
agente único en tres primitivas: parent_id, root_cause y skill_deps.yaml.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent.memory_db import MemoryDB
from tools.domain.evaluator import ROOT_CAUSES, detect_root_cause
from tools.domain.skill_graph import (
    deps_block,
    deps_edges_summary,
    deps_warnings,
    load_deps,
)


@pytest.fixture()
def db(tmp_path):
    d = MemoryDB(path=tmp_path / "t-graph.db")
    yield d
    d.close()


# --- migración y esquema ---

def test_harness_edits_has_graph_columns(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(harness_edits)")}
    assert "parent_id" in cols
    assert "root_cause" in cols


def test_add_edit_persists_parent_and_cause(db):
    db.add_harness_edit(
        proposal_id="p1", run_id="r1", component="context_memory",
        file="generated/rules.yaml", before="", after="a: 1", mode="replace",
        plan="plan", parent_id=None, root_cause=None,
    )
    db.set_harness_edit_decision("p1", "rejected", root_cause="no_improvement")
    row = db.get_harness_edit("p1")
    assert row["decision"] == "rejected"
    assert row["root_cause"] == "no_improvement"
    assert row["parent_id"] is None


# --- Idea 3: genealogía (EvoFlow) ---

def test_latest_accepted_edit_for_file(db):
    for pid, decision in (("a1", "rejected"), ("a2", "accepted"), ("a3", "pending")):
        db.add_harness_edit(
            proposal_id=pid, run_id="r1", component="context_memory",
            file="generated/skills.yaml", before="x", after="y", mode="replace",
            plan="p",
        )
        db.set_harness_edit_decision(pid, decision)
    # solo las ACEPTADAS son ancestros de contenido
    assert db.latest_accepted_edit_for_file("generated/skills.yaml") == "a2"
    assert db.latest_accepted_edit_for_file("generated/nope.yaml") is None


def test_genealogy_chain_root_to_leaf(db):
    # raíz -> hijo -> nieto sobre el mismo fichero
    chain = [("g1", None), ("g2", "g1"), ("g3", "g2")]
    for pid, parent in chain:
        db.add_harness_edit(
            proposal_id=pid, run_id="r1", component="tools_specs",
            file="archetypes/landing-page/rules.yaml", before="b", after="a",
            mode="replace", plan="p", parent_id=parent,
        )
        db.set_harness_edit_decision(pid, "accepted")
    tree = db.edit_genealogy("g3")
    assert [n["id"] for n in tree] == ["g1", "g2", "g3"]  # raíz primero
    assert [n["depth"] for n in tree] == [2, 1, 0]  # 0 = la edición consultada


def test_genealogy_single_root(db):
    db.add_harness_edit(
        proposal_id="solo", run_id="r1", component="context_memory",
        file="generated/workflows.yaml", before="", after="w: []",
        mode="replace", plan="p", parent_id=None,
    )
    tree = db.edit_genealogy("solo")
    assert len(tree) == 1 and tree[0]["id"] == "solo"


def test_rejected_causes_summary(db):
    for pid, cause in (("c1", "dev_degradation"), ("c2", "dev_degradation"),
                       ("c3", "no_improvement")):
        db.add_harness_edit(
            proposal_id=pid, run_id="r1", component="context_memory",
            file="f.yaml", before="", after="a", mode="replace", plan="p",
        )
        db.set_harness_edit_decision(pid, "rejected", root_cause=cause)
    summary = db.rejected_causes_summary()
    assert summary["dev_degradation"] == 2
    assert summary["no_improvement"] == 1


# --- Idea 2: atribución causal a nivel run (Who&When) ---

def test_detect_root_cause_maps_worst_axis():
    metrics = {"visual": 38, "creativity": 45, "functional": 90, "total": 60}
    cause, detail = detect_root_cause(metrics)
    assert cause == "visual_alignment"
    assert detail == "visual=38"


def test_detect_root_cause_none_when_all_healthy():
    metrics = {"visual": 80, "functional": 95, "task": 85}
    cause, _ = detect_root_cause(metrics)
    assert cause is None


def test_detect_root_cause_ignores_unknown_axes():
    metrics = {"novelty": 5, "total": 50}  # ejes fuera del enum
    cause, _ = detect_root_cause(metrics)
    assert cause is None


def test_root_causes_enum_complete():
    expected = {
        "visual_alignment", "creative_stale", "functional_broken",
        "structure_missing", "task_mismatch",
    }
    assert expected <= set(ROOT_CAUSES.values())


def test_edit_skill_links_parent_to_accepted_edit(tmp_path):
    """Integración EvoFlow: una propuesta nueva sobre un fichero ya editado con
    éxito hereda el id de esa edición como parent_id."""
    from config import PATHS
    from tools.domain.meta_editor import EditSkill

    file = "generated/test-graph-tmp.yaml"
    target = PATHS["domain"] / file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("base: v1\n")

    db0 = MemoryDB()
    try:
        db0.add_harness_edit(
            proposal_id="anc", run_id="r-anc", component="context_memory",
            file=file, before="", after="base: v1\n", mode="replace", plan="p",
        )
        db0.set_harness_edit_decision("anc", "accepted")
    finally:
        db0.close()

    tool = EditSkill()
    res = tool.run(
        component="context_memory", path=file,
        instruction="base: v2\nextra: true\n", mode="replace",
        run_id="r-graph",
    )
    assert res.startswith("OK") and "deriva de anc" in res

    db = MemoryDB()
    try:
        row = db.get_harness_edit(
            db.harness_edits(run_id="r-graph")[0]["id"]
        )
        assert row["parent_id"] == "anc"
        # limpieza
        db.conn.execute("DELETE FROM harness_edits WHERE file=?", (file,))
        db.conn.commit()
    finally:
        db.close()
    import shutil
    shutil.rmtree(PATHS["domain"] / ".proposals", ignore_errors=True)
    target.unlink(missing_ok=True)


# --- Idea 1: grafo de dependencias (Graph of Skills) ---

def test_load_deps_valid_shape():
    deps = load_deps()
    assert isinstance(deps, dict) and deps
    spec = deps.get("audit_page")
    assert isinstance(spec, dict)
    assert "generate_candidate" in (spec.get("depends_on") or [])


def test_deps_warnings_missing_prerequisite():
    warns = deps_warnings(["select_final"])
    assert any("select_final" in w and "audit_page" in w for w in warns)


def test_deps_warnings_no_violation_when_ordered():
    assert deps_warnings(["generate_candidate", "audit_page", "select_final"]) == []


def test_deps_repeat_guard_without_mutation():
    warns = deps_warnings(["generate_candidate", "audit_visual", "audit_visual"])
    assert any("repetido sin" in w and "audit_visual" in w for w in warns)


def test_deps_repeat_guard_ok_after_mutation():
    seq = ["generate_candidate", "audit_visual", "generate_candidate", "audit_visual"]
    warns = [w for w in deps_warnings(seq) if "repetido sin" in w]
    assert warns == []


def test_deps_block_renders_edges_and_warnings():
    block = deps_block(["select_final"])  # viola depends_on de select_final
    assert "VIOLACIONES DETECTADAS" in block
    assert "Aristas activas:" in block
