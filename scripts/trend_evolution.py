#!/usr/bin/env python3
"""Tendencia de evolución del harness a lo largo de las runs.

Lee memory/memory.db (fuente de verdad) y genera un reporte markdown con:
  - evolución temporal de best_score / baseline por run,
  - detección de cambios de versión del harness (tree_hash en runs.harness_hash),
  - qué archivos del harness cambiaron entre runs (harness_diff),
  - actividad meta-evolutiva por run (edit_skill, review_harness),
  - acumulación de lecciones por categoría,
  - comparación de runs del MISMO benchmark (mismo task_hash): ¿el harness
    mejora el score con el tiempo en tareas idénticas?

Uso:
    python -m scripts.trend_evolution
    python -m scripts.trend_evolution --min-score 50 --json
    python -m scripts.trend_evolution --benchmark 0b894166d3336435
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from config import PATHS

META_TOOLS = ("edit_skill", "review_harness")
LESSON_CATS = ("worked", "didnt", "try")


def _baseline(run_id: str, db: MemoryDB) -> float | None:
    """Total de H0 (nodo raíz del árbol), si existe."""
    nodes = db.nodes(run_id)
    if not nodes:
        return None
    roots = [n for n in nodes if not n.get("parent")]
    if roots:
        return roots[0]["metrics"].get("total")
    # sin parent explícito: el nodo más antiguo por id
    def _num(n):
        m = re.search(r"(\d+)$", n["node_id"] or "")
        return int(m.group(1)) if m else 0
    first = min(nodes, key=_num)
    return first["metrics"].get("total")


def collect(db: MemoryDB) -> list[dict]:
    """Junta por run: métricas, harness, actividad y lecciones."""
    rows = []
    for r in db.all_runs():
        run_id = r["id"]
        # descartar runs de test (sin arquetipo real o prefijos t-/tmp-)
        if not r.get("archetype") or run_id.startswith(("t-", "tmp-")):
            continue
        exps = db.experiments(run_id, limit=100000)
        lessons = db.lessons(run_id, max_items=100000)
        meta = Counter(e["action"] for e in exps if e["action"] in META_TOOLS)
        lesson_cats = Counter(l["category"] for l in lessons if l["category"])
        rows.append({
            "run_id": run_id,
            "archetype": r.get("archetype"),
            "task": r.get("task"),
            "task_hash": r.get("task_hash"),
            "started": r.get("started"),
            "baseline": _baseline(run_id, db),
            "best": r.get("best_score"),
            "harness_hash": r.get("harness_hash"),
            "harness_diff": r.get("harness_diff") or "",
            "meta": dict(meta),
            "lessons": dict(lesson_cats),
            "n_experiments": len(exps),
        })
    return sorted(rows, key=lambda x: x["started"] or "")


def _fmt_num(v) -> str:
    return f"{v:g}" if v is not None else "-"


def render_markdown(rows: list[dict], benchmark_hash: str | None) -> str:
    lines = [
        "# Tendencia de evolución del harness",
        "",
        f"Generado: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Runs analizadas: {len(rows)}",
        "",
        "## Evolución temporal de scores",
        "",
        "| Run | Fecha | Arquetipo | Baseline | Best | Δ | Harness (cambios) | Meta | Lecciones",
        "|---|---|---:|---:|---:|---:|---|---|---:|",
    ]
    prev_hash = None
    for r in rows:
        date = (r["started"] or "")[:10]
        delta = None
        if r["baseline"] is not None and r["best"] is not None:
            delta = r["best"] - r["baseline"]
        harness_cell = "-"
        if r["harness_hash"]:
            changed = r["harness_hash"] != prev_hash and prev_hash is not None
            if r["harness_diff"]:
                harness_cell = f"`{r['harness_hash'][:8]}` ({len(r['harness_diff'].split('; '))} archivos)"
            else:
                harness_cell = f"`{r['harness_hash'][:8]}`"
            prev_hash = r["harness_hash"]
        meta_cell = ", ".join(f"{k}={v}" for k, v in r["meta"].items()) or "-"
        lessons_cell = ", ".join(f"{k}={v}" for k, v in r["lessons"].items()) or "-"
        delta_txt = f"{delta:+g}" if delta is not None else "-"
        lines.append(
            f"| {r['run_id']} | {date} | {r['archetype']} | {_fmt_num(r['baseline'])} "
            f"| {_fmt_num(r['best'])} | {delta_txt} | {harness_cell} | {meta_cell} | {lessons_cell} |"
        )

    lines.extend(["", "## Cambios de versión del harness", ""])
    groups = defaultdict(list)
    for r in rows:
        if r["harness_hash"]:
            groups[r["harness_hash"]].append(r["run_id"])
    if not groups:
        lines.append("Sin información de versión (runs anteriores a la métrica).")
    else:
        for i, (h, runs) in enumerate(sorted(groups.items()), 1):
            lines.append(f"- **V{i}** `{h[:8]}` → {len(runs)} run(s): {', '.join(runs)}")
    for r in rows:
        if r["harness_diff"]:
            lines.append(f"  - En `{r['run_id']}`: {r['harness_diff']}")

    lines.extend(["", "## Actividad meta-evolutiva (edit_skill / review_harness)", ""])
    meta_rows = [r for r in rows if r["meta"]]
    if not meta_rows:
        lines.append("Ninguna run ejecutó meta-edición.")
    else:
        for r in meta_rows:
            lines.append(
                f"- `{r['run_id']}`: " + ", ".join(f"{k}={v}" for k, v in r["meta"].items())
            )

    lines.extend(["", "## Lecciones acumuladas por categoría", ""])
    agg = Counter()
    for r in rows:
        for cat, n in r["lessons"].items():
            agg[cat] += n
    for cat in list(LESSON_CATS) + [c for c in agg if c not in LESSON_CATS]:
        if agg[cat]:
            lines.append(f"- {cat}: {agg[cat]}")
    if not agg:
        lines.append("Sin lecciones registradas.")

    # benchmark: mismo task_hash
    if benchmark_hash:
        lines.extend([f"", "## Benchmark: mismo task_hash `{benchmark_hash}`", ""])
        bench = [r for r in rows if r["task_hash"] == benchmark_hash]
        lines.append(f"| Run | Fecha | Baseline | Best | Δ |")
        lines.append(f"|---|---:|---:|---:|---:|")
        for r in bench:
            delta = None
            if r["baseline"] is not None and r["best"] is not None:
                delta = r["best"] - r["baseline"]
            delta_txt = f"{delta:+g}" if delta is not None else "-"
            lines.append(
                f"| {r['run_id']} | {(r['started'] or '')[:10]} | {_fmt_num(r['baseline'])} "
                f"| {_fmt_num(r['best'])} | {delta_txt} |"
            )
        valid = [r for r in bench if r["baseline"] is not None and r["best"] is not None]
        if len(valid) >= 2:
            first, last = valid[0], valid[-1]
            best_delta = last["best"] - first["best"]
            lines.append("")
            lines.append(
                f"**Evolución del harness en este benchmark**: best pasó de "
                f"{_fmt_num(first['best'])} → {_fmt_num(last['best'])} "
                f"({best_delta:+g}), baseline {_fmt_num(first['baseline'])} → {_fmt_num(last['baseline'])} "
                f"a lo largo de {len(valid)} runs."
            )

    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Tendencia de evolución del harness entre runs")
    ap.add_argument("--min-score", type=float, default=0.0, help="Ignorar runs con best_score < umbral")
    ap.add_argument("--json", action="store_true", help="Emitir JSON además del markdown")
    ap.add_argument("--benchmark", default=None, help="Mostrar solo el bloque de un task_hash")
    args = ap.parse_args()

    db = MemoryDB()
    rows = collect(db)
    db.close()
    rows = [r for r in rows if (r["best"] or 0) >= args.min_score]

    md = render_markdown(rows, benchmark_hash=args.benchmark)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    out = PATHS["runs"] / f"trend_{ts}.md"
    out.write_text(md)
    print(md)
    print(f"\nReporte guardado en: {out}")

    if args.json:
        json_out = PATHS["runs"] / f"trend_{ts}.json"
        json_out.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        print(f"JSON guardado en: {json_out}")


if __name__ == "__main__":
    main()