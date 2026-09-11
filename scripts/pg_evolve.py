#!/usr/bin/env python3
"""Orquestador del bucle evolutivo del Procedural Graph (Algorithm 1,
§3.3 del paper "Procedural Graphs, Self-Evolving Execution Structures").

Ejecuta K iteraciones completas de evolución del grafo procedural:

    Rbest = baseline dev con el PG actual
    for k in 1..K:
        1. ROLLOUT train  -> run_single (el post-loop del agente ejecuta el
           PG Proposer; las propuestas quedan pending en harness_edits con
           component=pg_graph)
        2. PROPOSAL       -> propuesta pending de pg_graph.yaml de este run
        3. GATE           -> aplicar candidato a domain/generated/pg_graph.yaml,
           evaluar en dev, aceptar si R(Tval,k) > Rbest (actualizar Rbest) o
           revertir al `before` guardado (rejection memory) si no
        4. IMPACT         -> registrar diff + score + outcome en pg-impact.md

Uso:
    python -m scripts.pg_evolve \
        --train "landing-page:Landing para SaaS de IA" \
        --dev "saas-dashboard:Dashboard de métricas" \
        --iterations 3
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from config import PATHS

PG_FILE = "generated/pg_graph.yaml"


def _parse_task(spec: str) -> tuple[str, str]:
    archetype, _, task = spec.partition(":")
    task = task or f"Página web de tipo {archetype}"
    return archetype.strip(), task.strip()


def _best_total(run_dir: Path) -> float | None:
    """Proxy de R(Tsplit): mejor total de la run desde el transcript."""
    from scripts.run_battery import curve_from_transcript
    curve = curve_from_transcript(run_dir)
    totals = [p["total"] for p in curve if p.get("total") is not None]
    return max(totals) if totals else None


def _rollout(archetype: str, task: str, turns: int, max_cost: float,
             target_h: int, maintain: bool) -> object:
    """Corre una run del agente. Si maintain=False, desactiva el post-loop PG
    Proposer (no propone ediciones) — usado para evaluar el candidato en dev
    sin autocontaminar. El PG actual SÍ se inyecta siempre (PG_GRAPH_ENABLED=1)."""
    from scripts._common import run_single
    prev = os.environ.get("PG_MAINTAIN_ENABLED", "1")
    if not maintain:
        os.environ["PG_MAINTAIN_ENABLED"] = "0"
    try:
        return run_single(
            archetype=archetype,
            task=task,
            turns=turns,
            target_h=target_h,
            verbose=False,
            max_cost=max_cost,
        )
    finally:
        os.environ["PG_MAINTAIN_ENABLED"] = prev


def _apply_candidate(edit: dict) -> None:
    """Aplica la propuesta a domain/generated/pg_graph.yaml (promoción del staging)
    y resetea la caché del motor del grafo."""
    staged = PATHS["domain"] / ".proposals" / edit["id"] / "generated" / "pg_graph.yaml"
    if staged.exists():
        content = staged.read_text(errors="replace")
    else:
        content = edit.get("after") or ""
    if not content:
        return
    target = PATHS["domain"] / PG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    from tools.domain.pg_graph import reset_graph
    reset_graph()


def _rollback(edit: dict) -> None:
    """Revierte la propuesta: restaura `before` de pg_graph.yaml."""
    target = PATHS["domain"] / PG_FILE
    before = edit.get("before") or ""
    if before:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(before)
    elif target.exists():
        target.unlink()
    from tools.domain.pg_graph import reset_graph
    reset_graph()


def _append_impact(proposal_id: str, score: float | None, baseline: float | None,
                   decision: str, root_cause: str | None = None,
                   diff_nodes: int = 0, diff_edges: int = 0) -> None:
    imp = PATHS["memory"] / "wiki" / "pg-impact.md"
    if not imp.exists():
        imp.write_text("# PG impact log\n")
    cause = f" | root_cause={root_cause}" if root_cause else ""
    line = (
        f"\n- **{proposal_id}** [{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
        f"| Δnodes={diff_nodes} Δedges={diff_edges} "
        f"| R={score if score is not None else '-'} "
        f"(baseline={baseline if baseline is not None else '-'}) | "
        f"decision={decision}{cause}\n"
    )
    with imp.open("a") as f:
        f.write(line)


def _count_diff(edit: dict) -> tuple[int, int]:
    from tools.domain.pg_graph import apply_pg_edits
    _, errs = apply_pg_edits(edit.get("before") or "", {
        "add_nodes": [], "delete_nodes": [], "add_edges": [], "delete_edges": [],
    })
    if errs:
        return 0, 0
    try:
        import yaml
        a = yaml.safe_load(edit.get("after") or "{}")
        b = yaml.safe_load(edit.get("before") or "{}")
        na = len(a.get("nodes") or []) if isinstance(a, dict) else 0
        nb = len(b.get("nodes") or []) if isinstance(b, dict) else 0
        ea = len(a.get("edges") or []) if isinstance(a, dict) else 0
        eb = len(b.get("edges") or []) if isinstance(b, dict) else 0
        return na - nb, ea - eb
    except Exception:
        return 0, 0


def run_evolution(train_spec: str, dev_spec: str, iterations: int,
                  turns: int = 6, max_cost: float = 1.5,
                  target_h: int = 0, dry_run: bool = False) -> dict:
    """Algorithm 1 del paper sobre el grafo procedural. Devuelve resumen."""
    t_archetype, t_task = _parse_task(train_spec)
    d_archetype, d_task = _parse_task(dev_spec)

    summary = {
        "train": train_spec,
        "dev": dev_spec,
        "iterations": iterations,
        "baseline_dev": None,
        "iterations_log": [],
        "accepted": [],
        "rejected": [],
    }

    # Baseline Rbest: R(Tval,0) con el PG actual (sin nueva propuesta)
    dbg = _rollout(d_archetype, d_task, turns, max_cost, target_h, maintain=False)
    summary["baseline_dev"] = _best_total(dbg.run_dir)
    Rbest = summary["baseline_dev"]
    print(f"[baseline] dev score con PG actual = {Rbest}")

    for k in range(1, iterations + 1):
        print(f"\n=== Iteración {k}/{iterations} ===")
        # 1+2+3: rollout train — el post-loop del agente ejecuta el PG Proposer
        agent = _rollout(t_archetype, t_task, turns, max_cost, target_h, maintain=True)

        # Recuperar propuesta pending (pg_graph) generada por este run train
        db = MemoryDB()
        try:
            edits = db.harness_edits(decision="pending", run_id=agent.run_id)
            proposals = [e for e in edits if e.get("component") == "pg_graph"]
            if not proposals:
                print("  [proposer] no_action (sin propuesta de PG nueva)")
                summary["iterations_log"].append({"k": k, "proposal": None})
                continue
            edit = proposals[0]  # proposer atómico: 1 propuesta por iteración
            proposal_id = edit["id"]
            dn, de = _count_diff(edit)
            print(f"  [proposer] propuesta {proposal_id} (Δnodes={dn:+d} Δedges={de:+d})")
        finally:
            db.close()

        if dry_run:
            print("  [gate] DRY-RUN: no se aplica ni decide")
            summary["iterations_log"].append({"k": k, "proposal": proposal_id, "dry": True})
            continue

        # 5+6: aplicar candidato y evaluar en dev (PG'_k con maintain off)
        _apply_candidate(edit)
        dev_agent = _rollout(d_archetype, d_task, turns, max_cost, target_h, maintain=False)
        score = _best_total(dev_agent.run_dir)
        print(f"  [gate] R(Tval,{k}) = {score} vs Rbest = {Rbest}")

        db = MemoryDB()
        try:
            if score is not None and Rbest is not None and score > Rbest:
                # 7a: aceptar — promover (ya aplicado), actualizar Rbest
                db.set_harness_edit_decision(proposal_id, "accepted")
                Rbest = score
                _append_impact(proposal_id, score, Rbest, "accepted", diff_nodes=dn, diff_edges=de)
                summary["accepted"].append({"k": k, "id": proposal_id, "R": score, "dn": dn, "de": de})
                print(f"  [gate] ACCEPTED: PG promovido. Rbest -> {Rbest}")
            else:
                # 7b: rechazar — rollback a PG_{k-1} (rejection memory)
                root_cause = "no_improvement"
                _rollback(edit)
                db.set_harness_edit_decision(proposal_id, "rejected", root_cause=root_cause)
                _append_impact(proposal_id, score, Rbest, "rejected", root_cause, dn, de)
                summary["rejected"].append({"k": k, "id": proposal_id, "R": score, "dn": dn, "de": de})
                print(f"  [gate] REJECTED: PG revertido (no mejora baseline)")
        finally:
            db.close()

        summary["iterations_log"].append({
            "k": k, "proposal": proposal_id,
            "score": score, "rbest": Rbest,
        })

    # Reporte
    out = PATHS["runs"] / f"pg_evolve_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    lines = [
        "# Reporte de evolución del Procedural Graph",
        "",
        f"Generado: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Train: {train_spec}",
        f"Dev: {dev_spec}",
        f"Iteraciones: {iterations}",
        f"Baseline Rbest: {summary['baseline_dev']}",
        f"Aceptadas: {len(summary['accepted'])} · Rechazadas: {len(summary['rejected'])}",
        "",
    ]
    for r in summary["accepted"]:
        lines.append(f"- **ACCEPTED** k={r['k']} `{r['id']}` Δnodes={r['dn']:+d} Δedges={r['de']:+d} R={r['R']}")
    for r in summary["rejected"]:
        lines.append(f"- **REJECTED** k={r['k']} `{r['id']}` Δnodes={r['dn']:+d} Δedges={r['de']:+d} R={r['R']}")
    out.write_text("\n".join(lines))
    print(f"\nReporte guardado en: {out}")
    summary["report"] = str(out)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Bucle evolutivo del Procedural Graph (Algorithm 1)")
    ap.add_argument("--train", required=True, help="Tarea train 'arquetipo:tarea'")
    ap.add_argument("--dev", required=True, help="Tarea dev 'arquetipo:tarea'")
    ap.add_argument("--iterations", type=int, default=3, help="Número de iteraciones K")
    ap.add_argument("--turns", type=int, default=6, help="Turnos por rollout")
    ap.add_argument("--target-h", type=int, default=0)
    ap.add_argument("--max-cost", type=float, default=1.5, help="Presupuesto por rollout")
    ap.add_argument("--dry-run", action="store_true", help="Propone sin aplicar ni decidir gate")
    args = ap.parse_args()

    res = run_evolution(
        args.train, args.dev,
        iterations=args.iterations,
        turns=args.turns,
        max_cost=args.max_cost,
        target_h=args.target_h,
        dry_run=args.dry_run,
    )
    print("\nRESUMEN:")
    print(f"  baseline dev = {res['baseline_dev']}")
    print(f"  accepted = {res['accepted']}")
    print(f"  rejected = {res['rejected']}")


if __name__ == "__main__":
    main()