"""Tests de la capa de memoria SQLite y del script de limpieza."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from agent.state import _parse_lesson_blocks, Memory, SearchTree, TreeNode


def test_upsert_run_y_lesson_dedupe():
    db = MemoryDB()
    db.upsert_run("t-run", archetype="x", task="y", model="m", max_turns=5,
                  started="now", status="running")
    assert db.get_run("t-run")["archetype"] == "x"
    assert db.add_lesson("t-run", "worked", "hola mundo") is True
    assert db.add_lesson("t-run", "worked", "hola mundo") is False  # dedupe
    db.upsert_run("t-run", status="done", best_score=80.0, best_node="H2")
    assert db.get_run("t-run")["best_score"] == 80.0
    db.conn.execute("DELETE FROM runs WHERE id='t-run'")
    db.conn.execute("DELETE FROM lessons WHERE run_id='t-run'")
    db.conn.commit()
    db.close()


def test_experiments_y_nodes():
    db = MemoryDB()
    db.add_experiment("e-run", 1, "audit_page", "ok", "+1", "H0", "ts")
    db.add_experiment("e-run", 2, "generate_candidate", "ok", "", "H1", "ts")
    assert db.count_experiments() >= 2
    assert len(db.experiments("e-run")) >= 2
    db.upsert_node("e-run", "H0", None, "audit_page", {"total": 70}, "best_branch", "d")
    nodes = db.nodes("e-run")
    assert nodes and nodes[0]["metrics"]["total"] == 70
    db.delete_experiments("e-run")
    assert db.experiments("e-run") == []
    db.conn.execute("DELETE FROM tree_nodes WHERE run_id='e-run'")
    db.conn.commit()
    db.close()


def test_parse_lesson_blocks():
    text = "## What worked - 2026-08-15T12:00:00\nLección A\n## What didnt - 2026-08-15T13:00:00\nLección B"
    blocks = _parse_lesson_blocks(text)
    assert len(blocks) == 2
    assert blocks[0] == ("worked", "Lección A", "2026-08-15T12:00:00")
    assert blocks[1][0] == "didnt"
    assert _parse_lesson_blocks("texto suelto") == [("general", "texto suelto", None)]


def test_memory_db_integration():
    db = MemoryDB()
    mem = Memory(run_dir=Path("runs/tmp-mem"), db=db, run_id="tmp-mem")
    mem.append_incremental("## What worked - 2026-08-15T12:00:00\nX funcionó")
    assert db.lessons(run_id="tmp-mem")
    assert "X funcionó" in mem.read_global_lessons()
    mem.add_experiment(__import__("agent.state", fromlist=["Experiment"]).Experiment(
        id="t1", action="audit_page", result="ok", delta="+1"
    ))
    assert db.experiments("tmp-mem")
    db.conn.execute("DELETE FROM lessons WHERE run_id='tmp-mem'")
    db.conn.execute("DELETE FROM experiments WHERE run_id='tmp-mem'")
    db.conn.commit()
    db.close()


def test_search_tree_db_persist():
    db = MemoryDB()
    tree = SearchTree(path=Path("runs/tmp-tree/search_tree.json"), run_id="tmp-tree", db=db)
    tree.add(TreeNode(id="H0", parent=None, action="audit_page", metrics={"total": 60},
                      status="explored", description=""))
    reloaded = SearchTree(path=Path("runs/tmp-tree/search_tree.json"), run_id="tmp-tree", db=db)
    assert "H0" in reloaded.nodes
    assert reloaded.nodes["H0"].metrics["total"] == 60
    db.conn.execute("DELETE FROM tree_nodes WHERE run_id='tmp-tree'")
    db.conn.commit()
    db.close()


def test_cleanup_select_oldest():
    from scripts.cleanup_runs import select_oldest
    runs = [Path(f"runs/20260815T11{n}00--x") for n in range(5)]
    oldest = select_oldest(runs, 2)
    assert [r.name for r in oldest] == [runs[0].name, runs[1].name, runs[2].name]
    assert select_oldest(runs, 10) == []
    assert select_oldest(runs, 0) == []


if __name__ == "__main__":
    for fn in [test_upsert_run_y_lesson_dedupe, test_experiments_y_nodes,
               test_parse_lesson_blocks, test_memory_db_integration,
               test_search_tree_db_persist, test_cleanup_select_oldest]:
        fn()
        print(f"OK {fn.__name__}")
    print("Todos los tests de memoria OK")