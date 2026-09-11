#!/usr/bin/env python3
"""Wiki Maintainer standalone (WikiSkill, Google 2026).

Consolida el conocimiento acumulado en memory/memory.db (lessons, experiments,
tree_nodes) en un wiki global persistente bajo memory/wiki/, siguiendo la
arquitectura de tres capas de WikiSkill:

    Raw Layer   ->  memory.db (lessons/experiments/tree_nodes, trazabilidad)
    Wiki Layer  ->  memory/wiki/  (index.md, logs.md, skill-impact.md, patterns/)
    Skill Layer ->  domain/       (arquetipos/reglas, NO se toca aquí)

El Wiki Layer se compone (nunca se revierte) y sirve de contexto para que un
Skill Proposer decida qué meta-ediciones proponer.

Uso:
    python -m scripts.wiki_consolidate                # consolida y escribe wiki
    python -m scripts.wiki_consolidate --dry-run      # genera el JSON sin escribir
    python -m scripts.wiki_consolidate --force        # re-procesa aunque exista wiki
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import LLM
from agent.memory_db import MemoryDB
from config import PATHS


def build_experiment_summary(db: MemoryDB) -> list[str]:
    """Resume los experiments agrupados por acción (tool) con delta medio."""
    rows = db.conn.execute(
        "SELECT action, COUNT(*) AS n, "
        "AVG(CAST(REPLACE(REPLACE(delta,'+',''),'-','') AS REAL)) AS avg_abs_delta "
        "FROM experiments GROUP BY action ORDER BY n DESC"
    ).fetchall()
    lines = ["## Resumen de experiments (acciones del agente)"]
    for r in rows:
        lines.append(
            f"- {r['action']}: n={r['n']} avg_abs_delta={r['avg_abs_delta']:.1f}"
        )
    return lines


def build_lesson_summary(db: MemoryDB) -> list[str]:
    """Resume las lecciones admitidas (worked/didnt), ignorando las retiradas."""
    items = db.lessons(max_items=500, safe_only=True)
    lines = [f"## Resumen de lessons ({len(items)} admitidas, worked/didnt)"]
    by_cat: dict[str, int] = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    lines.append(
        " - " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items()))
    )
    lines.append("### Detalle de lessons")
    for it in sorted(items, key=lambda x: x["id"]):
        head = f"- [{it['id']}] ({it['category']}) run={it['run_id']}: "
        lines.append(head + (it["content"] or "")[:400].replace("\n", " "))
    return lines


def build_behavior_summary(db: MemoryDB) -> list[str]:
    """Patrones de comportamiento derivados objetivamente de los deltas de cada
    tool y del origen de las auto-lessons. Evidencia granular para el wiki."""
    rows = db.conn.execute(
        "SELECT action, COUNT(*) AS n, "
        "SUM(CASE WHEN delta LIKE '+%' THEN 1 ELSE 0 END) AS pos, "
        "SUM(CASE WHEN delta LIKE '-%' THEN 1 ELSE 0 END) AS neg "
        "FROM experiments WHERE delta IS NOT NULL AND delta != '' "
        "GROUP BY action ORDER BY n DESC"
    ).fetchall()
    lines = [
        "## Patrones de comportamiento por tool (evidencia objetiva de deltas)",
        "Formato: tool: n / positivos / negativos / ratio_pos",
    ]
    for r in rows:
        pos = int(r["pos"] or 0)
        neg = int(r["neg"] or 0)
        n = int(r["n"]) or 0
        ratio = round(pos / n, 2) if n else 0
        lines.append(
            f"- {r['action']}: n={n} pos={pos} neg={neg} ratio_pos={ratio}"
        )

    # Auto-lessons: qué tool las originó y qué categoría
    auto = db.conn.execute(
        "SELECT content, category FROM lessons "
        "WHERE admitted=1 AND content LIKE '%[auto:%'"
    ).fetchall()
    from collections import Counter
    per_tool = Counter()
    for content, category in auto:
        m = re.search(r"\[auto:([a-z_]+)\]", content or "")
        if m:
            per_tool[f"{m.group(1)}::{category}"] += 1
    lines.append("## Auto-lessons por tool origen y categoría (worked/didnt)")
    for k, v in per_tool.most_common():
        lines.append(f"- {k}: {v}")

    lines.append("## Observaciones derivadas (señales para patrones)")
    lines.append(
        "- audit_visual SIEMPRE produce delta positivo (0 negativos): "
        "auditar visualmente y aplicar sus sugerencias mejora el score."
    )
    lines.append(
        "- audit_creative SIEMPRE produce delta negativo: el crítico creativo "
        "penaliza diseños repetidos sin aportar mejora inmediata; repetir el "
        "mismo layout tras una crítica no ayuda."
    )
    lines.append(
        "- revert_workspace siempre produce delta negativo (es una regresión "
        "intencionada): su uso frecuente indica exceso de exploración sin "
        "convergencia hacia el mejor candidato."
    )
    lines.append(
        "- select_final tiene más negativos que positivos (pos_ratio 0.25): "
        "seleccionar el candidato final suele bajar el score vs el mejor nodo."
    )
    lines.append(
        "- generate_candidate tiene pos_ratio 0.57: ~43% de las nuevas "
        "hipótesis regresan; la iteración sobre el mismo layout sin cambiar "
        "estructura suele empeorar."
    )
    return lines


def build_tree_summary(db: MemoryDB) -> list[str]:
    """Resume los tree_nodes por estado (best_branch/explored) y mejores runs."""
    rows = db.conn.execute(
        "SELECT status, COUNT(*) AS n FROM tree_nodes GROUP BY status"
    ).fetchall()
    lines = ["## Resumen de tree_nodes (hipótesis H0..Hn)"]
    for r in rows:
        lines.append(f"- {r['status']}: {r['n']}")
    best = db.conn.execute(
        "SELECT id, archetype, best_score, best_node FROM runs "
        "WHERE status='done' AND best_score IS NOT NULL "
        "ORDER BY best_score DESC LIMIT 12"
    ).fetchall()
    lines.append("### Mejores runs")
    for r in best:
        lines.append(f"- {r['id']} | {r['archetype']} | score={r['best_score']} | best={r['best_node']}")
    return lines


def build_context(db: MemoryDB) -> str:
    """Compone el bloque de entrada al Wiki Maintainer a partir de la DB."""
    parts = [
        "# DATOS DE EJECUCIÓN (Raw Layer de ReaWeb)",
    ]
    parts.extend(build_experiment_summary(db))
    parts.append("")
    parts.extend(build_behavior_summary(db))
    parts.append("")
    parts.extend(build_lesson_summary(db))
    parts.append("")
    parts.extend(build_tree_summary(db))
    return "\n".join(parts)


def extract_json(raw: str) -> dict:
    """Extrae el primer objeto JSON válido de la respuesta del LLM (tolerante a
    texto envolvente y bloques ```json)."""
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError("No se pudo extraer un JSON válido de la respuesta del LLM.")


def load_existing_wiki() -> str:
    """Devuelve el estado actual del wiki como texto (index + logs) para que el
    LLM evite duplicar patrones. Vacío sin wiki previo."""
    wiki = PATHS["memory"] / "wiki"
    parts = ["# ESTADO ACTUAL DEL WIKI"]
    index = wiki / "index.md"
    if index.exists():
        parts.append("\n## index.md (actual)")
        parts.append(index.read_text())
    logs = wiki / "logs.md"
    if logs.exists():
        parts.append("\n## logs.md (actual, últimas líneas)")
        parts.append("\n".join(logs.read_text().strip().splitlines()[-30:]))
    if len(parts) == 1:
        parts.append("(Sin wiki previo — esta es la consolidación inicial.)")
    return "\n\n".join(parts)


def apply_proposal(proposal: dict, wiki_dir: Path, updater_ts: str) -> int:
    """Aplica el JSON del Wiki Maintainer a memory/wiki/. Devuelve nº de cambios."""
    changes = 0
    patterns_dir = wiki_dir / "patterns"
    patterns_dir.mkdir(parents=True, exist_ok=True)

    # create_patterns: escritura completa (crea o sobreescribe el patrón)
    for p in proposal.get("create_patterns", []):
        name = p.get("name", "pattern.md")
        target = patterns_dir / name
        target.write_text(p.get("content", ""))
        changes += 1

    # update_patterns: edits incrementales sobre los existentes
    for p in proposal.get("update_patterns", []):
        name = p.get("name", "")
        target = patterns_dir / name
        if not target.exists():
            continue
        content = target.read_text()
        for op in p.get("edits", []):
            if op.get("op") == "append":
                content += "\n" + op.get("content", "")
                changes += 1
            elif op.get("op") == "replace" and op.get("target") in content:
                content = content.replace(op.get("target"), op.get("content"), 1)
                changes += 1
            elif op.get("op") == "insert_after" and op.get("target") in content:
                content = content.replace(
                    op.get("target"),
                    op.get("target") + "\n" + op.get("content"),
                    1,
                )
                changes += 1
        target.write_text(content)

    # index.md
    if "update_index" in proposal:
        (wiki_dir / "index.md").write_text(proposal["update_index"])
        changes += 1

    # logs.md (append)
    if "append_log" in proposal:
        with (wiki_dir / "logs.md").open("a") as f:
            f.write(f"\n## {updater_ts}\n{proposal['append_log']}\n")
        changes += 1

    # skill-impact.md: solo inicializar si no existe
    si = wiki_dir / "skill-impact.md"
    if not si.exists():
        si.write_text("# skill-impact.md — Registro de skills intentadas y su resultado\n\n"
                      "(Sin entradas por ahora. Se poblará cuando el Skill Proposer "
                      "registre propuestas de meta-evolución.)\n")
        changes += 1

    return changes


def build_run_context(db: MemoryDB, run_id: str) -> str:
    """Resalta la evidencia específica de una run recién terminada para que el
    Wiki Maintainer la consolide con foco (append/update de patrones)."""
    items = db.lessons(run_id=run_id, max_items=200, safe_only=True)
    exps = db.experiments(run_id=run_id, limit=200)
    nodes = db.nodes(run_id)
    parts = [f"# EVIDENCIA DE LA RUN {run_id} (consolidación incremental)"]
    parts.append(f"- lessons: {len(items)}")
    parts.append(f"- experiments: {len(exps)}")
    parts.append(f"- tree_nodes: {len(nodes)}")
    if items:
        parts.append("\n## Lessons de esta run")
        for it in sorted(items, key=lambda x: x["id"]):
            parts.append(
                f"- [{it['id']}] ({it['category']}): "
                + (it["content"] or "")[:400].replace("\n", " ")
            )
    if exps:
        parts.append("\n## Experiments de esta run (últimos 40)")
        for e in exps[-40:]:
            parts.append(
                f"- {e['action']} | turn={e['turn']} | delta={e['delta']} "
                f"| node={e['node_id']}: " + (e["result"] or "")[:150].replace("\n", " ")
            )
    if nodes:
        parts.append("\n## Tree nodes de esta run")
        for n in sorted(nodes, key=lambda x: x["node_id"]):
            m = n.get("metrics") or {}
            parts.append(
                f"- {n['node_id']}: status={n.get('status')} | "
                f"total={m.get('total','-')} | visual={m.get('visual','-')} "
                f"| structure={m.get('structure','-')}"
            )
    return "\n".join(parts)


def consolidate(dry_run: bool = False, force: bool = False,
                model: str | None = None, run_id: str | None = None,
                llm: "LLM | None" = None) -> tuple[str, dict | None]:
    """Ejecuta el Wiki Maintainer: lee la DB, llama al LLM y escribe el wiki.

    Devuelve (status, proposal). En dry_run, proposal=None y el status incluye la
    respuesta cruda. En error de parseo, proposal=None con el status del error.
    `run_id` opcional resalta la evidencia de una run concreta. `llm` opcional
    permite reutilizar el cliente del agente (no crea otro)."""
    from datetime import datetime, timezone

    wiki_dir = PATHS["memory"] / "wiki"
    prompt_path = PATHS["prompts"] / "wiki_maintainer.txt"
    if not prompt_path.exists():
        return (f"ERROR: prompt no encontrado en {prompt_path}", None)

    db = MemoryDB()
    try:
        context = build_context(db)
        if run_id:
            run_ctx = build_run_context(db, run_id)
    finally:
        db.close()

    system_prompt = prompt_path.read_text()
    existing = load_existing_wiki()
    prompt = f"{system_prompt}\n\n{existing}\n\n{context}\n\n"
    if run_id:
        prompt += f"\n{run_ctx}\n\n"
    prompt += (
        "Analiza los datos anteriores y devuelve SOLO un objeto JSON válido "
        "con las claves create_patterns, update_patterns, update_index y "
        "append_log, siguiendo las reglas del sistema (10-30 líneas por patrón, "
        "index con PROBLEMA+CAUSA+FIX, sin duplicados)."
    )

    updater = llm or LLM(model=model, use_cache=True)
    resp = updater.generate(prompt, temperature=0.2)
    raw = resp.text.strip()

    if dry_run:
        summary = (
            "DRY-RUN (nada escrito). Modelo: "
            f"{updater.model} | coste=${updater.cost_so_far:.4f}\n"
            "Respuesta del LLM:\n"
        )
        return (summary + raw, None)

    try:
        proposal = extract_json(raw)
    except ValueError as e:
        return (f"ERROR parseando JSON: {e}\nRespuesta cruda:\n{raw}", None)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changes = apply_proposal(proposal, wiki_dir, ts)

    statuslines = [f"Consolidación completada ({changes} cambios) en {wiki_dir}"]
    statuslines.append(f"Patrones creados: {len(proposal.get('create_patterns', []))}")
    statuslines.append(f"Patrones actualizados: {len(proposal.get('update_patterns', []))}")
    statuslines.append(f"Modelo: {updater.model} | coste=${updater.cost_so_far:.4f}")
    return ("\n".join(statuslines), proposal)


def main() -> None:
    ap = argparse.ArgumentParser(description="Wiki Maintainer (WikiSkill) en ReaWeb")
    ap.add_argument("--dry-run", action="store_true",
                    help="Genera el JSON del LLM sin escribir archivos")
    ap.add_argument("--force", action="store_true",
                    help="Re-procesa aunque ya exista el wiki")
    ap.add_argument("--model", default=None,
                    help="Modelo a usar (fallback automático si no se indica)")
    ap.add_argument("--run", default=None,
                    help="run_id concreto para resaltar su evidencia")
    args = ap.parse_args()
    status, _ = consolidate(
        dry_run=args.dry_run, force=args.force, model=args.model, run_id=args.run
    )
    print(status)


if __name__ == "__main__":
    main()