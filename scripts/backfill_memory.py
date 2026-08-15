#!/usr/bin/env python3
"""Backfill de las runs existentes a la base de datos de memoria (SQLite).

Lee cada runs/<id>/ (run_config.json, search_tree.json, transcript.jsonl y
lessons_incremental.md) y rellena las tablas runs, tree_nodes, experiments y
lessons de memory/memory.db. Idempotente (upsert). También recupera el
huérfano runs/lessons_incremental.md (raíz), que antes nunca llegaba a global.

Uso:
    python -m scripts.backfill_memory                  # todo
    python -m scripts.backfill_memory --run <run_id>   # una run concreta
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.harness_snapshot import task_hash as _task_hash
from agent.memory_db import MemoryDB
from config import PATHS


def _parse_ts(line: str) -> str | None:
    try:
        return json.loads(line).get("ts")
    except Exception:
        return None


def backfill_run(db: MemoryDB, run_dir: Path, verbose: bool = True) -> dict:
    run_id = run_dir.name
    stats = {"run": 0, "nodes": 0, "experiments": 0, "lessons": 0}

    # 1) runs: run_config.json + end del transcript
    cfg = {}
    cfg_path = run_dir / "run_config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception:
            cfg = {}
    fields = {
        "archetype": cfg.get("archetype"),
        "task": cfg.get("task"),
        "task_hash": cfg.get("task_hash") or (_task_hash(cfg.get("task", "")) if cfg.get("task") else None),
        "model": cfg.get("model"),
        "max_turns": cfg.get("max_turns"),
        "started": cfg.get("started"),
        "harness_hash": (cfg.get("harness") or {}).get("end") or (cfg.get("harness") or {}).get("start"),
        "harness_diff": "; ".join((cfg.get("harness") or {}).get("diff", [])),
    }
    db.upsert_run(run_id=run_id, **{k: v for k, v in fields.items() if v is not None})
    stats["run"] = 1

    # experiments: reconstruir desde cero (idempotente)
    db.delete_experiments(run_id)

    # 2) tree_nodes + best del search_tree.json
    tree_path = run_dir / "search_tree.json"
    if tree_path.exists():
        try:
            data = json.loads(tree_path.read_text())
            for node_id, nd in data.get("nodes", {}).items():
                db.upsert_node(
                    run_id=run_id,
                    node_id=node_id,
                    parent=nd.get("parent"),
                    action=nd.get("action", ""),
                    metrics=nd.get("metrics", {}),
                    status=nd.get("status", "explored"),
                    description=nd.get("description", ""),
                )
                stats["nodes"] += 1
        except Exception as e:
            if verbose:
                print(f"  [warn] search_tree.json de {run_id}: {e}")

    # 3) experiments + finished/best desde transcript.jsonl
    trans = run_dir / "transcript.jsonl"
    finished = None
    best_total = None
    best_node = None
    if trans.exists():
        best_so_far = None
        pending_tools: list[dict] = []
        for line in trans.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = e.get("kind")
            if kind == "tool":
                pending_tools.append({
                    "turn": e.get("turn", 0),
                    "tool": e.get("tool", ""),
                    "result": str(e.get("result", ""))[:200],
                    "ts": e.get("ts"),
                })
            elif kind == "eval":
                # mejor candidato definitivo: última entrada eval por candidato
                if e.get("total") is not None:
                    total = e["total"]
                    prev = best_so_far if best_so_far is not None else total
                    delta = total - prev
                    best_so_far = max(best_so_far or 0, total)
                    best_total = total
                    best_node = e.get("candidate") or best_node
                    # asociar el eval a la tool generate_candidate/audit_page previa
                    node_id = e.get("candidate")
                    for pt in reversed(pending_tools):
                        if pt["tool"] in ("generate_candidate", "audit_page"):
                            pt["delta"] = f"{delta:+.1f}"
                            pt["node_id"] = node_id
                            break
            elif kind == "end":
                finished = e.get("ts") or finished
        for pt in pending_tools:
            db.add_experiment(
                run_id=run_id,
                turn=pt["turn"],
                action=pt["tool"],
                result=pt["result"],
                delta=pt.get("delta", ""),
                node_id=pt.get("node_id"),
                ts=pt["ts"],
            )
            stats["experiments"] += 1
        # mejor del árbol (autoritativo), no del transcript
        best = db.nodes(run_id)
        if best:
            top = max(best, key=lambda n: n["metrics"].get("total", -1))
            best_total = top["metrics"].get("total")
            best_node = top["node_id"]

    db.upsert_run(
        run_id=run_id,
        finished=finished,
        best_score=best_total,
        best_node=best_node,
        status="done",
    )

    # 4) lessons desde lessons_incremental.md de la run
    inc = run_dir / "lessons_incremental.md"
    if inc.exists() and inc.stat().st_size > 0:
        from agent.state import _parse_lesson_blocks

        for category, content, ts in _parse_lesson_blocks(inc.read_text()):
            if db.add_lesson(run_id=run_id, category=category, content=content, ts=ts):
                stats["lessons"] += 1

    if verbose:
        print(f"  {run_id}: {stats}")
    return stats


def backfill_orphan_lessons(db: MemoryDB, verbose: bool = True) -> int:
    """Recupera runs/lessons_incremental.md (raíz, huérfano) a global."""
    from agent.state import _parse_lesson_blocks

    orphan = PATHS["runs"] / "lessons_incremental.md"
    if not orphan.exists() or orphan.stat().st_size == 0:
        return 0
    count = 0
    for category, content, ts in _parse_lesson_blocks(orphan.read_text()):
        if db.add_lesson(run_id="global", category=category, content=content, ts=ts):
            count += 1
    if verbose and count:
        print(f"  runs/lessons_incremental.md (huérfano): {count} lecciones -> global")
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill de runs a la base de memoria")
    ap.add_argument("--run", default=None, help="run_id concreto (o backfill de todas)")
    ap.add_argument("--quiet", action="store_true", help="No imprimir detalle")
    args = ap.parse_args()

    db = MemoryDB()
    total = {"run": 0, "nodes": 0, "experiments": 0, "lessons": 0}

    if args.run:
        run_dir = PATHS["runs"] / args.run
        if not run_dir.exists():
            print(f"ERROR: no existe runs/{args.run}")
            return
        st = backfill_run(db, run_dir, verbose=not args.quiet)
        for k, v in st.items():
            total[k] += v
    else:
        dirs = sorted(d for d in PATHS["runs"].iterdir() if d.is_dir())
        for d in dirs:
            st = backfill_run(db, d, verbose=not args.quiet)
            for k, v in st.items():
                total[k] += v

    total["lessons"] += backfill_orphan_lessons(db, verbose=not args.quiet)

    print("\n=== Resumen backfill ===")
    print(f"  runs: {total['run']} | tree_nodes: {total['nodes']} "
          f"| experiments: {total['experiments']} | lessons: {total['lessons']}")
    print(f"  Totales en DB: runs={len(db.all_runs())} lessons={db.count_lessons()} "
          f"experiments={db.count_experiments()} nodes={db.count_nodes()}")
    db.close()


if __name__ == "__main__":
    main()