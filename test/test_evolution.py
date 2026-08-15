"""Tests de las métricas de evolución: snapshot del harness, task_hash,
backfill con delta y tendencia entre runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import harness_snapshot
from agent.harness_snapshot import diff_snapshots, lessons_hash, snapshot, task_hash
from agent.memory_db import MemoryDB
from config import PATHS


def test_snapshot_hashes_files():
    s = snapshot()
    assert s["n_files"] > 0
    assert s["tree_hash"]
    assert any(k.endswith(".py") for k in s["files"])
    assert s["files"] == snapshot()["files"]  # estable


def test_snapshot_includes_docs_and_memory():
    s = snapshot()
    assert any(k.startswith("Docs/") for k in s["files"]), "Docs/ debe estar versionado"
    assert s["n_files"] > sum(1 for k in s["files"] if k.startswith("Docs/"))
    assert "memory/lessons.db" in s["files"]  # la memoria es parte viva del harness


def test_lessons_hash_derived_from_db():
    db = MemoryDB()
    db.add_lesson("t-evo2", "worked", "leccion unica evo2")
    h = lessons_hash()
    assert h and len(h) == 16
    db.conn.execute("DELETE FROM lessons WHERE run_id='t-evo2' AND content='leccion unica evo2'")
    db.conn.commit()
    db.close()
    assert lessons_hash() != h, "cambiar lecciones debe cambiar lessons_hash"


def test_diff_snapshots_detects_change():
    a = {"files": {"domain/archetypes/x/rules.yaml": "abc", "a.txt": "x"}}
    b = {"files": {"domain/archetypes/x/rules.yaml": "def", "b.txt": "y"}}
    lines = diff_snapshots(a, b)
    joined = "\n".join(lines)
    assert "modificado domain/archetypes/x/rules.yaml" in joined
    assert "añadido b.txt" in joined
    assert "eliminado a.txt" in joined
    assert diff_snapshots(a, a) == []


def test_task_hash_stable_and_normalized():
    assert task_hash("  Hola   mundo ") == task_hash("hola mundo")
    assert len(task_hash("cualquier tarea")) == 16


def test_db_run_has_harness_columns():
    db = MemoryDB()
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(runs)")}
    for col in ("task_hash", "harness_hash", "harness_diff"):
        assert col in cols, col
    db.upsert_run("t-evo", archetype="x", task="t", task_hash="h1",
                  harness_hash="h2", harness_diff="~ archivo", status="done")
    run = db.get_run("t-evo")
    assert run["task_hash"] == "h1"
    assert run["harness_hash"] == "h2"
    assert run["harness_diff"] == "~ archivo"
    db.conn.execute("DELETE FROM runs WHERE id='t-evo'")
    db.conn.commit()
    db.close()


def test_backfill_computes_delta():
    """El backfill asigna delta y node_id a generate_candidate/audit_page."""
    run_id = "tmp-evo-backfill"
    run_dir = PATHS["runs"] / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_config.json").write_text(json.dumps({
        "archetype": "landing-page", "task": "landing", "task_hash": "th1",
        "model": "m", "max_turns": 5, "started": "2026-08-15T10:00:00",
        "harness": {"start": "aaa", "end": "bbb", "diff": ["~ domain/x.py"]},
    }))
    (run_dir / "search_tree.json").write_text(json.dumps({
        "nodes": {
            "H0": {"parent": None, "metrics": {"total": 70}},
            "H1": {"parent": "H0", "metrics": {"total": 80}},
        }
    }))
    trans = [
        {"kind": "tool", "turn": 1, "tool": "generate_candidate", "result": "ok", "ts": "t1"},
        {"kind": "eval", "candidate": "H0", "total": 70, "ts": "t2"},
        {"kind": "tool", "turn": 2, "tool": "generate_candidate", "result": "ok", "ts": "t3"},
        {"kind": "eval", "candidate": "H1", "total": 80, "ts": "t4"},
        {"kind": "end", "ts": "t5"},
    ]
    (run_dir / "transcript.jsonl").write_text(
        "\n".join(json.dumps(e) for e in trans)
    )

    from scripts.backfill_memory import backfill_run
    db = MemoryDB()
    backfill_run(db, run_dir, verbose=False)
    run = db.get_run(run_id)
    assert run["task_hash"] == "th1"
    assert run["harness_hash"] == "bbb"
    assert "domain/x.py" in (run["harness_diff"] or "")
    exps = db.experiments(run_id, limit=10)
    gen = sorted([e for e in exps if e["action"] == "generate_candidate"], key=lambda e: e["turn"])
    assert len(gen) == 2
    assert gen[0]["node_id"] == "H0"
    assert gen[0]["delta"] == "+0.0"
    assert gen[1]["node_id"] == "H1"
    assert gen[1]["delta"] == "+10.0"
    assert db.get_run(run_id)["best_score"] == 80

    # limpieza
    for r in exps:
        db.conn.execute("DELETE FROM experiments WHERE run_id=?", (run_id,))
    db.conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    db.conn.execute("DELETE FROM tree_nodes WHERE run_id=?", (run_id,))
    db.conn.commit()
    db.close()
    import shutil
    shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    for fn in [test_snapshot_hashes_files, test_snapshot_includes_docs_and_memory,
               test_lessons_hash_derived_from_db, test_diff_snapshots_detects_change,
               test_task_hash_stable_and_normalized, test_db_run_has_harness_columns,
               test_backfill_computes_delta]:
        fn()
        print(f"OK {fn.__name__}")
    print("Todos los tests de evolución OK")