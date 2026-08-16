#!/usr/bin/env python3
"""Acceptance gate de la meta-evolución (Algorithm 1 de AutoDesign).

Una propuesta `edit_skill` pending se aprueba SOLO si mejora la puntuación de
benchmark en train y NO degrada en dev:

    Accept(H') <=> J_train(H') > J_train(H)  ∧  J_dev(H') >= J_dev(H)

Donde J(H) es un benchmark corto (short-run) de la tarea train/dev. Si se
aprueba, el cambio se aplica a domain/ (el staging se promueve); si no, se
revierte al contenido `before` guardado y se descarta.

Uso:
    python -m scripts.gate_harness_edit                          # todas las pending
    python -m scripts.gate_harness_edit --proposal <id>          # solo una
    python -m scripts.gate_harness_edit --train-archetype ... --train-task ...
    python -m scripts.gate_harness_edit --dry-run                # decide sin aplicar
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from config import PATHS

GATE_DEFAULTS = {
    "turns": 3,
    "target_h": 1,
}


def _short_run_score(archetype: str, task: str, turns: int, target_h: int) -> float | None:
    """Devuelve el mejor total de una short-run de la tarea (proxy de J(H))."""
    from scripts._common import run_single
    from scripts.run_battery import curve_from_transcript

    agent = run_single(
        archetype=archetype,
        task=task,
        turns=turns,
        target_h=target_h,
        verbose=False,
        max_cost=1.0,
    )
    curve = curve_from_transcript(agent.run_dir)
    totals = [p["total"] for p in curve if p.get("total") is not None]
    return max(totals) if totals else None


def _apply_after(edit: dict) -> None:
    """Promueve la propuesta: aplica `after` sobre domain/<file>."""
    target = (PATHS["domain"] / edit["file"]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(edit["after"])


def _revert(edit: dict) -> None:
    """Revierte la propuesta: restaura `before` en domain/<file>."""
    target = (PATHS["domain"] / edit["file"]).resolve()
    if edit.get("before"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit["before"])
    elif target.exists():
        target.unlink()


def gate_proposal(edit: dict, train_archetype: str, train_task: str,
                  dev_archetype: str, dev_task: str, turns: int, target_h: int,
                  dry_run: bool = False) -> dict:
    """Evalúa una propuesta en train/dev y decide accepted|rejected.

    Devuelve un dict con decisión, scores antes/después y motivo.
    """
    def J(arq: str, task: str) -> float | None:
        return _short_run_score(arq, task, turns, target_h)

    before = {"train": J(train_archetype, train_task), "dev": J(dev_archetype, dev_task)}

    if not dry_run:
        _apply_after(edit)

    after = {"train": J(train_archetype, train_task), "dev": J(dev_archetype, dev_task)}

    if before["train"] is None or after["train"] is None:
        accept, reason = False, "sin score de train (baseline no medible)"
    elif after["train"] <= before["train"]:
        accept, reason = False, f"train no mejora ({before['train']:g} -> {after['train']:g})"
    elif before["dev"] is not None and after["dev"] is not None and after["dev"] < before["dev"]:
        accept, reason = False, f"dev degrada ({before['dev']:g} -> {after['dev']:g})"
    else:
        accept, reason = True, f"train {before['train']:g}->{after['train']:g}, dev {before['dev'] if before['dev'] is not None else '-'}->{after['dev'] if after['dev'] is not None else '-'}"

    decision = "accepted" if accept else "rejected"
    if not dry_run:
        if not accept:
            _revert(edit)
        _persist(edit["id"], decision)

    return {
        "proposal": edit["id"],
        "file": edit["file"],
        "component": edit.get("component"),
        "decision": decision,
        "reason": reason,
        "before": before,
        "after": after,
    }


def _persist(proposal_id: str, decision: str) -> None:
    db = MemoryDB()
    try:
        db.set_harness_edit_decision(proposal_id, decision)
    finally:
        db.close()


def _cleanup_staging(edit: dict) -> None:
    staged = PATHS["domain"] / ".proposals" / edit["id"]
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Acceptance gate de meta-ediciones del harness")
    ap.add_argument("--proposal", default=None, help="ID de propuesta concreta (todas si se omite)")
    ap.add_argument("--train-archetype", default="landing-page")
    ap.add_argument("--train-task", default="Landing page moderna para un SaaS de IA")
    ap.add_argument("--dev-archetype", default="ecommerce")
    ap.add_argument("--dev-task", default="Tienda online de sneakers con carrito")
    ap.add_argument("--turns", type=int, default=GATE_DEFAULTS["turns"])
    ap.add_argument("--target-h", type=int, default=GATE_DEFAULTS["target_h"])
    ap.add_argument("--dry-run", action="store_true", help="Decide sin aplicar cambios ni persistir")
    args = ap.parse_args()

    db = MemoryDB()
    try:
        edits = db.harness_edits(decision="pending", run_id=args.proposal) if args.proposal else db.harness_edits(decision="pending")
        if args.proposal:
            edits = [e for e in edits if e["id"] == args.proposal]
    finally:
        db.close()

    if not edits:
        print("No hay propuestas pending.")
        return

    results = []
    for edit in edits:
        r = gate_proposal(
            edit,
            train_archetype=args.train_archetype,
            train_task=args.train_task,
            dev_archetype=args.dev_archetype,
            dev_task=args.dev_task,
            turns=args.turns,
            target_h=args.target_h,
            dry_run=args.dry_run,
        )
        results.append(r)
        _cleanup_staging(edit)
        print(
            f"[{r['decision'].upper():8s}] {r['proposal']} {r['file']} "
            f"(train {r['before']['train']}->{r['after']['train']}, "
            f"dev {r['before']['dev']}->{r['after']['dev']}) — {r['reason']}"
        )

    accepted = sum(1 for r in results if r["decision"] == "accepted")
    out = PATHS["runs"] / f"gate_{datetime.now().strftime('%Y%m%dT%H%M%S')}.md"
    lines = [
        "# Reporte del acceptance gate",
        "",
        f"Generado: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Propuestas evaluadas: {len(results)} · Aceptadas: {accepted}",
        "",
    ]
    for r in results:
        lines.append(
            f"- **{r['decision']}** `{r['proposal']}` {r['file']} [{r['component']}] — {r['reason']}"
        )
    out.write_text("\n".join(lines))
    print(f"\nReporte guardado en: {out}")


if __name__ == "__main__":
    main()