#!/usr/bin/env python3
"""Orquestador del bucle evolutivo WikiSkill (Algorithm 1, §A.1 del paper).

Ejecuta K iteraciones completas de evolución de skills:

    Rbest = baseline dev con skills actuales
    for k in 1..K:
        1. ROLLOUT train  -> run_single (inyecta skills activos; el post-loop del
           agente ya consolida el wiki y ejecuta el Skill Proposer)
        2. PROPOSAL       -> propuestas pending nuevas (component=skills) del run
        3. GATE           -> aplicar candidato a domain/skills/, evaluar en dev,
           aceptar si R(Tval,k) > Rbest (actualizar Rbest) o revertir si no
        4. IMPACT         -> registrar diff + score + outcome en skill-impact.md

Uso:
    python -m scripts.wiki_evolve \
        --train "landing-page:Landing para SaaS de IA" \
        --dev "saas-dashboard:Dashboard de métricas" \
        --iterations 3
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from config import PATHS


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
    """Corre una run del agente. Si maintain=False, desactiva el post-loop
    WikiSkill (no consolida wiki ni propone) — usado para evaluar el candidato
    en dev sin autocontaminar. Los skills activos SÍ se inyectan siempre
    (_wiki_enabled se mantiene 1)."""
    from scripts._common import run_single
    prev = os.environ.get("WIKI_MAINTAIN_ENABLED", "1")
    if not maintain:
        os.environ["WIKI_MAINTAIN_ENABLED"] = "0"
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
        os.environ["WIKI_MAINTAIN_ENABLED"] = prev


def _apply_candidate(edit: dict) -> None:
    """Aplica la propuesta a domain/skills/ (promoción del staging)."""
    staged = PATHS["domain"] / ".proposals" / edit["id"] / "skills"
    if not staged.exists():
        # fallback: reconstruir desde el registro de la DB
        name = _skill_name(edit)
        if not name:
            return
        d = PATHS["skills"] / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(edit.get("after") or "")
        return
    dest = PATHS["skills"]
    dest.mkdir(parents=True, exist_ok=True)
    for item in staged.iterdir():
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _skill_name(edit: dict) -> str | None:
    file = (edit.get("file") or "").replace("\\", "/")
    parts = file.split("/")
    if len(parts) >= 3 and parts[0] == "skills" and parts[2].endswith("SKILL.md"):
        return parts[1]
    return None


def _rollback(edit: dict) -> None:
    """Revierte la propuesta: restaura `before` de SKILL.md (patch) o elimina el
    skill (create si no existía antes)."""
    name = _skill_name(edit)
    if not name:
        return
    d = PATHS["skills"] / name
    if edit.get("mode") == "patch" and (d / "SKILL.md").exists():
        before = edit.get("before") or ""
        if before:
            (d / "SKILL.md").write_text(before)
        else:
            (d / "SKILL.md").unlink(missing_ok=True)
    else:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _append_impact(proposal_id: str, skill: str, score: float | None,
                   baseline: float | None, decision: str,
                   root_cause: str | None = None) -> None:
    si = PATHS["memory"] / "wiki" / "skill-impact.md"
    cause = f" | root_cause={root_cause}" if root_cause else ""
    line = (
        f"\n- **{proposal_id}** [{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
        f"| skill={skill} | R={score if score is not None else '-'} "
        f"(baseline={baseline if baseline is not None else '-'}) | "
        f"decision={decision}{cause}\n"
    )
    with si.open("a") as f:
        f.write(line)


def run_evolution(train_spec: str, dev_spec: str, iterations: int,
                  turns: int = 6, max_cost: float = 1.5,
                  target_h: int = 0, dry_run: bool = False) -> dict:
    """Algorithm 1 completo. Devuelve resumen con decisiones por iteración."""
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

    # Baseline Rbest: R(Tval,0) con los skills activos actuales (sin nueva propuesta)
    dbg = _rollout(d_archetype, d_task, turns, max_cost, target_h, maintain=False)
    summary["baseline_dev"] = _best_total(dbg.run_dir)
    Rbest = summary["baseline_dev"]
    print(f"[baseline] dev score con skills actuales = {Rbest}")

    for k in range(1, iterations + 1):
        print(f"\n=== Iteración {k}/{iterations} ===")
        # 1+2+3: rollout train — el post-loop agente consolida wiki Y propone skill
        agent = _rollout(t_archetype, t_task, turns, max_cost, target_h, maintain=True)

        # Recuperar propuestas pending (skills) generadas por este run train
        db = MemoryDB()
        try:
            edits = db.harness_edits(decision="pending", run_id=agent.run_id)
            proposals = [e for e in edits if e.get("component") == "skills"]
            if not proposals:
                print("  [proposer] no_action (sin propuesta de skill nueva)")
                summary["iterations_log"].append({"k": k, "proposal": None})
                continue
            edit = proposals[0]  # proposer atómico: 1 propuesta por iteración
            proposal_id = edit["id"]
            skill = _skill_name(edit) or "?"
            mode = edit.get("mode")
            print(f"  [proposer] propuesta {proposal_id} skill={skill} mode={mode}")
        finally:
            db.close()

        if dry_run:
            print("  [gate] DRY-RUN: no se aplica ni decide")
            summary["iterations_log"].append({"k": k, "proposal": proposal_id, "skill": skill, "dry": True})
            continue

        # 5+6: aplicar candidato y evaluar en dev (S'_k con maintain off)
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
                _append_impact(proposal_id, skill, score, Rbest, "accepted")
                summary["accepted"].append({"k": k, "id": proposal_id, "skill": skill, "R": score})
                print(f"  [gate] ACCEPTED: skill '{skill}' promovido. Rbest -> {Rbest}")
            else:
                # 7b: rechazar — rollback a S_{k-1}
                root_cause = "no_improvement"
                _rollback(edit)
                db.set_harness_edit_decision(proposal_id, "rejected", root_cause=root_cause)
                _append_impact(proposal_id, skill, score, Rbest, "rejected", root_cause)
                summary["rejected"].append({"k": k, "id": proposal_id, "skill": skill, "R": score})
                print(f"  [gate] REJECTED: skill '{skill}' revertido (no mejora baseline)")
        finally:
            db.close()

        summary["iterations_log"].append({
            "k": k, "proposal": proposal_id, "skill": skill,
            "score": score, "rbest": Rbest,
        })

    # Reporte
    out = PATHS["runs"] / f"wiki_evolve_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    lines = [
        "# Reporte de evolución WikiSkill",
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
        lines.append(f"- **ACCEPTED** k={r['k']} `{r['id']}` skill={r['skill']} R={r['R']}")
    for r in summary["rejected"]:
        lines.append(f"- **REJECTED** k={r['k']} `{r['id']}` skill={r['skill']} R={r['R']}")
    out.write_text("\n".join(lines))
    print(f"\nReporte guardado en: {out}")
    summary["report"] = str(out)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Bucle evolutivo WikiSkill (Algorithm 1)")
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