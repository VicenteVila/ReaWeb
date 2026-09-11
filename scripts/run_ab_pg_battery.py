#!/usr/bin/env python3
"""Driver A/B de validación estadística del Procedural Graph (PG+PEARL).

Ejecuta el mismo arquetipo/tarea con la condición `on` (PG_GRAPH_ENABLED=1) y
`off` (PG_GRAPH_ENABLED=0) en round-robin por réplica, para mitigar la deriva
temporal de la API, y deja un marker JSON por (cond, rep) con: best, baseline,
curva, coste y nº de tools. Los markers permiten **retomar** una batería
interrumpida (skips) y auditar a posteriori qué condición se ejecutó de verdad.

La condición se pasa al harness vía `os.environ["PG_GRAPH_ENABLED"]`; el agente
la lee en la construcción de cada run (ver .agent/agent.py, __init__), y queda
registrada por run en `runs/<id>/run_config.json` -> `flags.pg_enabled`,
para verificar que el toggle llegó al harness (lección del fallo documentado en
Docs/PG_AB_VALIDATION.md: la constante de config se congelaba en el import).

Uso:
    REPS=5 python -m scripts.run_ab_pg_battery
    REPS=3 ARCH=saas-dashboard python -m scripts.run_ab_pg_battery
    BATTERY_OUT=/tmp/opencode/battery_results python -m scripts.run_ab_pg_battery
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from config import PATHS
from scripts._common import run_single
from scripts.run_battery import curve_from_transcript

OUT = Path(os.environ.get("BATTERY_OUT", PATHS["runs"] / "battery_results"))
OUT.mkdir(parents=True, exist_ok=True)

# respaldo de seguridad del legado de workspace/current (por si acaso)
BACKUP = Path(os.environ.get("BATTERY_BACKUP", PATHS["workspace"] / "ws_backup"))
BACKUP.mkdir(parents=True, exist_ok=True)

TASKS = [
    ("portfolio-creative",
     "Portfolio creativo de una diseñadora UX: Hero con nombre y CTA, Selected Work"
     " con hover effects, Case Studies (Problem→Process→Solution→Results), About,"
     " Services, Process, Testimonials, Contact con formulario. Dark mode, tipografía"
     " display, micro-interacciones."),
]


def reset_workspace(arch: str) -> None:
    """Vacía workspace/current para que H0 nazca del arquetipo y no del legado."""
    cur = PATHS["current"]
    if not cur.exists():
        return
    dst = BACKUP / f"{arch}_{int(time.time())}"
    shutil.copytree(cur, dst, dirs_exist_ok=True)
    for item in cur.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def run_one(arch: str, task: str, cond: str, rep: int) -> dict:
    """Ejecuta una run (si no hay marker) y persiste el resumen JSON."""
    mark = OUT / f"{arch}_{cond}_rep{rep}.json"
    if mark.exists():
        print(f"[skip] {arch} {cond} rep{rep}", flush=True)
        return json.loads(mark.read_text())

    reset_workspace(arch)
    # la condición llega al harness vía entorno; el agente la lee por run
    os.environ["PG_GRAPH_ENABLED"] = "1" if cond == "on" else "0"
    os.environ["WIKI_ENABLED"] = "0"

    a = run_single(arch, task, turns=6, max_cost=2.0, verbose=False, quick=False,
                   target_h=int(os.environ.get("TARGET_H", "0")))
    curve = curve_from_transcript(a.run_dir)
    totals = [c["total"] for c in curve if c.get("total") is not None]
    n_tools = 0
    trans = a.run_dir / "transcript.jsonl"
    if trans.exists():
        n_tools = len([1 for l in (json.loads(x) for x in trans.read_text().splitlines())
                       if l.get("kind") == "tool"])
    res = {
        "arch": arch, "task": task, "cond": cond, "rep": rep,
        "run_id": a.run_id, "best": max(totals, default=None),
        "baseline": curve[0]["total"] if curve else None,
        "curve": [c["total"] for c in curve],
        "turns": a.turn, "cost": a.budget.cost_so_far, "tools": n_tools,
    }
    mark.write_text(json.dumps(res, ensure_ascii=False))
    print(f"[done] {arch} {cond} rep{rep} -> {a.run_id} best={res['best']} "
          f"cost=${res['cost']:.3f} tools={n_tools}", flush=True)
    return res


if __name__ == "__main__":
    reps = int(os.environ.get("REPS", "2"))
    arch_env = os.environ.get("ARCH")
    archs = [(a, t) for a, t in TASKS if not arch_env or a == arch_env]
    results = []
    for arch, task in archs:
        for rep in range(1, reps + 1):
            for cond in ("on", "off"):
                results.append(run_one(arch, task, cond, rep))
    (OUT / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print("BATTERY_COMPLETE", flush=True)