#!/usr/bin/env python3
"""Runner de batería: ejecuta varias runs y resume las curvas H0→Hn en un reporte.

Uso:
    python -m scripts.run_battery \
        --run "landing-page:Landing para SaaS de IA" \
        --run "ecommerce:Tienda online de sneakers" \
        --turns 6

    python -m scripts.run_battery --config battery.yaml

Genera en runs/ un reporte markdown con, por run: baseline, mejor score,
mejora (%), factores audit y curva de evolución de nodos.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import yaml

from scripts._common import run_single


def parse_cli_runs(runs: list[str]) -> dict:
    """Convierte items 'arquetipo:tarea' en un dict {arquetipo: tarea}."""
    out = OrderedDict()
    for item in runs:
        archetype, _, task = item.partition(":")
        if not archetype:
            continue
        out[archetype] = task or f"Página web de tipo {archetype}"
    return out


def load_runs_config(path: Path) -> dict:
    """Lee config de batería en YAML: {archetype: task}, con claves globales opcionales."""
    raw = yaml.safe_load(path.read_text()) or {}
    runs = OrderedDict(raw.get("runs", {}))
    return runs


def curve_from_transcript(run_dir: Path) -> list[dict]:
    """Extrae los nodos evaluados del transcript: [{id, total, delta}]."""
    curve = []
    trans = run_dir / "transcript.jsonl"
    if not trans.exists():
        return curve
    for line in trans.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("kind") == "eval" and e.get("total") is not None:
            curve.append({"id": e.get("candidate"), "total": e["total"], "delta": e.get("delta"), "version": e.get("version")})
    # deduplicar: si audit_page confirma una hipótesis, se queda la última entrada por id
    by_id: dict = {}
    for c in curve:
        by_id[c["id"]] = c

    def _sort_key(c: dict) -> int:
        import re
        m = re.search(r"(\d+)$", c["id"] or "")
        return int(m.group(1)) if m else 0

    return [by_id[k] for k in sorted(by_id, key=lambda k: _sort_key(by_id[k]))]


def summarize_run(archetype: str, task: str, turn: int, verbose: bool = True, target_h: int = 0, initial_url: str = "") -> dict:
    """Ejecuta una run y devuelve su resumen sintético."""
    agent = run_single(
        archetype=archetype,
        task=task,
        turns=turn,
        verbose=verbose,
        target_h=target_h,
        initial_url=initial_url,
    )
    curve = curve_from_transcript(agent.run_dir)
    best = max(curve, key=lambda x: x["total"]) if curve else None
    baseline = curve[0]["total"] if curve else None
    delta = (best["total"] - baseline) if (best and baseline is not None) else None
    improvement = (delta / baseline * 100) if (baseline and baseline > 0) else None
    return {
        "run_id": agent.run_id,
        "archetype": archetype,
        "task": task,
        "run_dir": str(agent.run_dir),
        "baseline": baseline,
        "best": best,
        "delta": delta,
        "improvement_pct": improvement,
        "curve": [f"{c['id']}={c['total']}" for c in curve],
        "turns_used": agent.turn,
        "turns_max": turn,
        "cost_usd": agent.budget.cost_so_far,
    }


def render_report(results: list[dict]) -> str:
    lines = [
        "# Reporte de batería ReaWeb Harness",
        "",
        f"Fecha: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## Resumen",
        "",
        "| Arquetipo | Baseline | Mejor | Δ | Mejora % | Turnos | Coste |",
        "|---|---:|---:|---:|---:|:---:|---:|",
    ]
    for r in results:
        imp = f"{r['improvement_pct']:.1f}" if r["improvement_pct"] is not None else "-"
        best_txt = r["best"]["total"] if r["best"] else "-"
        delta_txt = f"{r['delta']:+d}" if r["delta"] is not None else "-"
        lines.append(
            f"| {r['archetype']} | {r['baseline']} | {best_txt} "
            f"| {delta_txt} | {imp} | "
            f"{r['turns_used']}/{r['turns_max']} | ${r['cost_usd']:.4f} |"
        )
    lines.extend(["", "## Evolución por run", ""])
    for r in results:
        lines.append(f"### {r['archetype']} (`{r['run_id']}`)")
        lines.append(f"Tarea: {r['task']}")
        lines.append(f"Curva: {' → '.join(r['curve']) if r['curve'] else '(sin nodos evaluados)'}")
        lines.append(f"Run dir: `{r['run_dir']}`")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Ejecuta una batería de runs y resume las curvas H0→Hn")
    parser.add_argument("--run", action="append", default=[], help="Item 'arquetipo:tarea' (repetible)")
    parser.add_argument("--config", type=Path, default=None, help="YAML {runs: {arquetipo: tarea}}")
    parser.add_argument("--turns", type=int, default=8, help="Presupuesto de iteraciones por run")
    parser.add_argument("--target-h", type=int, default=0,
                        help="Hipótesis objetivo por run (p. ej. --target-h 3 => H0..H3)")
    parser.add_argument("--max-cost", type=float, default=2.0, help="Presupuesto máx USD por run")
    parser.add_argument("--model", default=None, help="Modelo Gemini")
    parser.add_argument("--url", default="", help="URL de referencia para todas las runs (adaptar como H0)")
    parser.add_argument("--quiet", action="store_true", help="No imprimir detalle de cada run")
    parser.add_argument("--gate", action="store_true",
                        help="Ejecutar el acceptance gate tras la batería sobre propuestas pending")
    args = parser.parse_args()

    if args.config:
        runs = load_runs_config(args.config)
    else:
        runs = parse_cli_runs(args.run)
    if not runs:
        parser.error("Indica al menos una run con --run 'arquetipo:tarea' o --config battery.yaml")

    results = []
    for archetype, task in runs.items():
        print(f"\n### Batería: {archetype} — {task}")
        summary = summarize_run(
            archetype=archetype,
            task=task,
            turn=args.turns,
            verbose=not args.quiet,
            target_h=args.target_h,
            initial_url=args.url,
        )
        results.append(summary)

    report = render_report(results)
    from datetime import datetime
    out = Path(f"runs/reporte_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md")
    out.write_text(report)
    print("\n" + "=" * 60)
    print(report)
    print(f"\nReporte guardado en: {out}")

    if args.gate:
        from scripts.gate_harness_edit import main as gate_main
        gate_main()


if __name__ == "__main__":
    main()