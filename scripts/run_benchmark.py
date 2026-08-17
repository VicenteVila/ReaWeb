#!/usr/bin/env python3
"""Benchmark de referencia re-ejecutable: permite lanzar de nuevo una tarea fija
(referencia) y comparar su resultado contra las ejecuciones históricas con el
mismo task_hash, para medir si el harness ha mejorado con el tiempo.

Uso:
    python -m scripts.run_benchmark \
        --archetype knowledge-graph \
        --task "Crea una landing centrada en un grafo de conocimientos..." \
        --turns 22 --target-h 5

    # solo comparar históricos de un benchmark sin lanzar una run nueva
    python -m scripts.run_benchmark --compare --task-hash 0b894166d3336435

Genera runs/reporte_benchmark_<ts>.md comparando la run actual contra los
históricos del mismo task_hash (baseline, best, Δ).
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.harness_snapshot import task_hash
from agent.memory_db import MemoryDB
from config import PATHS


def _baseline(run_id: str, nodes_by_run: dict) -> float | None:
    """Total de H0 vía tree_nodes (nodo sin parent, o el primero por id)."""
    nodes = nodes_by_run.get(run_id) or []
    roots = [n for n in nodes if not n.get("parent")]
    if roots:
        return roots[0]["metrics"].get("total")

    def _num(n):
        m = re.search(r"(\d+)$", n["node_id"] or "")
        return int(m.group(1)) if m else 0

    if nodes:
        return min(nodes, key=_num)["metrics"].get("total")
    return None


def _f(v, sign: bool = False) -> str:
    if v is None:
        return "-"
    return f"{v:+g}" if sign else f"{v:g}"


def render(hist: list[dict], current: dict | None, baseline: float | None) -> str:
    lines = [
        "# Reporte de benchmark ReaWeb",
        "",
        f"Generado: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## Históricos del mismo benchmark",
        "",
        "| Run | Fecha | Arquetipo | Baseline | Best | Δ | Modelo |",
        "|---|---|---:|---:|---:|---:|:---:|",
    ]
    best_scores = []
    for r in hist:
        base = r.get("_baseline")
        delta = None
        if base is not None and r.get("best_score") is not None:
            delta = r["best_score"] - base
        if r.get("best_score") is not None:
            best_scores.append(r["best_score"])
        lines.append(
            f"| {r['id']} | {(r.get('started') or '')[:10]} | {r.get('archetype')} "
            f"| {_f(base)} | {_f(r.get('best_score'))} | {_f(delta, sign=True)} | {r.get('model')} |"
        )
    if current:
        delta = None
        if baseline is not None and current.get("best_score") is not None:
            delta = current["best_score"] - baseline
        if current.get("best_score") is not None:
            best_scores.append(current["best_score"])
        lines.append(
            f"| **{current['id']} (actual)** | {(current.get('started') or '')[:10]} | {current.get('archetype')} "
            f"| {_f(baseline)} | {_f(current.get('best_score'))} | {_f(delta, sign=True)} | {current.get('model')} |"
        )

    lines.extend(["", "## Evolución", ""])
    if best_scores:
        lines.append(
            f"- Mejor de históricos: {max(best_scores)} · peor: {min(best_scores)} "
            f"· media: {sum(best_scores)/len(best_scores):.1f} ({len(best_scores)} runs)"
        )
    if len(best_scores) >= 2:
        lines.append(
            f"- Tendencia best: {best_scores[0]:g} → {best_scores[-1]:g} "
            f"({best_scores[-1] - best_scores[0]:+g})"
        )
    if current:
        b = current.get("best_score")
        if b is not None and best_scores:
            avg = sum(best_scores) / len(best_scores)
            lines.append(
                f"- Run actual ({b:g}) vs media histórica ({avg:.1f}): "
                f"{'MEJORA sobre la media' if b >= avg else 'por debajo de la media'}"
            )
    else:
        lines.append("(sin run actual: usa --archetype/--task para lanzar una nueva)")
    return "\n".join(lines)


def load_benchmark(db: MemoryDB, th: str) -> tuple[list[dict], dict]:
    """Históricos (con baseline) y los nodos de todas las runs en un dict."""
    nodes_by_run = {}
    for run_id in {r["id"] for r in db.all_runs()}:
        nodes_by_run[run_id] = db.nodes(run_id)
    hist = []
    for r in db.all_runs():
        if r.get("task_hash") != th:
            continue
        r["_baseline"] = _baseline(r["id"], nodes_by_run)
        hist.append(r)
    hist.sort(key=lambda x: x.get("started") or "")
    return hist, nodes_by_run


def main():
    ap = argparse.ArgumentParser(description="Benchmark de referencia re-ejecutable")
    ap.add_argument("--archetype", default=None, help="Arquetipo de la run de referencia")
    ap.add_argument("--task", default=None, help="Tarea de referencia (idéntica cada vez)")
    ap.add_argument("--turns", type=int, default=20, help="Presupuesto de iteraciones")
    ap.add_argument("--target-h", type=int, default=0, help="Hipótesis objetivo")
    ap.add_argument("--max-cost", type=float, default=5.0, help="Presupuesto máx USD")
    ap.add_argument("--compare", action="store_true", help="Solo comparar históricos (no lanzar run)")
    ap.add_argument("--task-hash", default=None, help="task_hash concreto (para --compare)")
    ap.add_argument("--suite", action="store_true",
                    help="Ejecutar la suite completa de benchmark/tasks.yaml")
    ap.add_argument("--leaderboard", action="store_true",
                    help="Tras la suite, regenerar benchmark/leaderboard.json + .md")
    ap.add_argument("--json-out", default=None,
                    help="Ruta donde escribir los resultados como JSON (para CI)")
    args = ap.parse_args()

    db = MemoryDB()

    if args.suite:
        return _run_suite(args, db)

    if args.compare:
        th = args.task_hash or task_hash(args.task or "")
        hist, _ = load_benchmark(db, th)
        db.close()
        report = render(hist, None, None)
        print(report)
        out = PATHS["runs"] / f"reporte_benchmark_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
        out.write_text(report)
        print(f"\nReporte guardado en: {out}")
        if args.leaderboard:
            import json
            bests = [r["best_score"] for r in hist if r.get("best_score") is not None]
            agg = {
                "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
                "task_hash": th,
                "n_tasks": len(bests),
                "n_passed": len(bests),
                "mean_best": round(sum(bests) / len(bests), 1) if bests else None,
                "results": [
                    {"task_id": "?", "archetype": r.get("archetype"), "task_hash": th,
                     "baseline": r.get("_baseline"), "best": r.get("best_score"),
                     "run_id": r["id"], "started": (r.get("started") or "")[:10],
                     "model": r.get("model")}
                    for r in hist
                ],
            }
            if args.json_out:
                Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.json_out).write_text(json.dumps(agg, ensure_ascii=False, indent=2))
            _write_leaderboard(agg)
        return

    if not args.archetype or not args.task:
        db.close()
        ap.error("Para lanzar una run de referencia usa --archetype y --task")

    from scripts._common import run_single
    from scripts.run_battery import curve_from_transcript

    agent = run_single(
        archetype=args.archetype,
        task=args.task,
        turns=args.turns,
        max_cost=args.max_cost,
        target_h=args.target_h,
        verbose=True,
    )
    curve = curve_from_transcript(agent.run_dir)
    baseline = curve[0]["total"] if curve else None

    th = task_hash(args.task)
    hist, _ = load_benchmark(db, th)
    current = db.get_run(agent.run_id)
    db.close()

    report = render(hist, current, baseline)
    print(report)
    out = PATHS["runs"] / f"reporte_benchmark_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    out.write_text(report)
    print(f"\nReporte guardado en: {out}")


def _run_suite(args, db):
    """Ejecuta benchmark/tasks.yaml tarea a tarea y (opcional) regenera el
    leaderboard agregado en benchmark/."""
    import json

    import yaml

    from scripts._common import run_single
    from scripts.run_battery import curve_from_transcript

    suite_file = PATHS["root"] / "benchmark" / "tasks.yaml"
    if not suite_file.exists():
        db.close()
        raise SystemExit(f"Falta la suite: {suite_file}")
    suite = yaml.safe_load(suite_file.read_text()).get("suite", [])
    print(f"Suite: {len(suite)} tareas ({datetime.now().isoformat(timespec='seconds')})\n")

    results = []
    for task_def in suite:
        tid = task_def["id"]
        print(f"{'='*60}\n[{tid}] {task_def['archetype']}: {task_def['task'][:70]}...")
        try:
            agent = run_single(
                archetype=task_def["archetype"],
                task=task_def["task"],
                turns=task_def.get("turns", 16),
                max_cost=args.max_cost,
                target_h=task_def.get("target_h", 0),
                verbose=False,
            )
            curve = curve_from_transcript(agent.run_dir)
            best = curve[-1]["total"] if curve else None
            baseline = curve[0]["total"] if curve else None
        except Exception as e:
            print(f"  [ERROR] {e}")
            best = baseline = None
        th = task_hash(task_def["task"])
        results.append({
            "task_id": tid,
            "archetype": task_def["archetype"],
            "task_hash": th,
            "baseline": baseline,
            "best": best,
            "run_id": getattr(agent, "run_id", None) if "agent" in locals() else None,
            "started": datetime.now().isoformat(timespec="seconds"),
            "model": agent.model if "agent" in locals() else None,
        })
        print(f"  => best={best} baseline={baseline} hash={th}")

    agg = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "task_hash": results[0]["task_hash"] if results else None,
        "n_tasks": len(results),
        "n_passed": sum(1 for r in results if r["best"] is not None),
        "mean_best": round(sum(r["best"] for r in results if r["best"] is not None)
                          / max(1, sum(1 for r in results if r["best"] is not None)), 1),
        "results": results,
    }
    print(f"\n=== AGREGADO: {agg['n_passed']}/{agg['n_tasks']} tareas, "
          f"media best {agg['mean_best']} ===")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(agg, ensure_ascii=False, indent=2))
        print(f"JSON en: {out}")

    if args.leaderboard:
        _write_leaderboard(agg)
    db.close()


def _write_leaderboard(agg: dict) -> None:
    """Escribe benchmark/leaderboard.json y leaderboard.md (commit automático CI)."""
    import json

    bench_dir = PATHS["root"] / "benchmark"
    bench_dir.mkdir(parents=True, exist_ok=True)

    json_path = bench_dir / "leaderboard.json"
    prev = {}
    if json_path.exists():
        try:
            prev = json.loads(json_path.read_text())
        except Exception:
            prev = {}
    json_path.write_text(json.dumps(agg, ensure_ascii=False, indent=2))

    md_lines = [
        "# Leaderboard ReaWeb",
        "",
        f"Generado: {agg['generated']} · {agg['n_passed']}/{agg['n_tasks']} tareas "
        f"· media best **{agg['mean_best'] if agg.get('mean_best') is not None else '-'}**",
        "",
        "| Tarea | Arquetipo | Baseline | Best | Δ | Run |",
        "|---|---|---:|---:|---:|:---:|",
    ]
    for r in sorted(agg["results"], key=lambda x: -(x["best"] or 0)):
        delta = ""
        if r.get("best") is not None and r.get("baseline") is not None:
            delta = f"{r['best'] - r['baseline']:+g}"
        md_lines.append(
            f"| {r['task_id']} | {r['archetype']} | {_f(r.get('baseline'))} "
            f"| {_f(r.get('best'))} | {delta} | {r['run_id'] or '-'} |"
        )
    prev_mean = prev.get("mean_best")
    if prev_mean is not None:
        md_lines.append(
            f"\nMedia best vs anterior: {agg['mean_best']} vs {prev_mean} "
            f"({agg['mean_best'] - prev_mean:+g})"
        )
    (bench_dir / "leaderboard.md").write_text("\n".join(md_lines) + "\n")
    print(f"Leaderboard actualizado: {bench_dir / 'leaderboard.md'}")


if __name__ == "__main__":
    main()