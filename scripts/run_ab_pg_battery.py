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

# Señales de que la QUOTA (o un muro de límite) está muerta y reintentar las
# runs restantes solo quema tiempo: la run ya reintentó 7x dentro del LLM.
_QUOTA_MARKERS = ("429", "resource_exhausted", "quota", "rate limit",
                  "ratelimit", "tokens per minute", "itpm", "413")


def _is_quota_error(msg: str) -> bool:
    m = (msg or "").lower()
    return any(k in m for k in _QUOTA_MARKERS)


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
    """Ejecuta una run (si no hay marker VÁLIDO) y persiste el resumen JSON.
    Los markers con error (p. ej. cuota agotada) NO se saltan al reanudar: se
    reintentan, porque una run fallida no es una run hecha. Solo los markers con
    best no-None se consideran completados."""
    mark = OUT / f"{arch}_{cond}_rep{rep}.json"
    if mark.exists():
        prev = json.loads(mark.read_text())
        if prev.get("best") is not None and not prev.get("error"):
            print(f"[skip] {arch} {cond} rep{rep}", flush=True)
            return prev

    reset_workspace(arch)
    # la condición llega al harness vía entorno; el agente la lee por run
    os.environ["PG_GRAPH_ENABLED"] = "1" if cond == "on" else "0"
    os.environ["WIKI_ENABLED"] = "0"
    # Integridad A/B: UN solo modelo en toda la batería. Sin esto, cuando la
    # cuota del modelo preferido muere, el fallback degrada a un modelo distinto
    # y el dataset acaba con modelos MEZCLADOS (no comparable; `valid`=False).
    os.environ["LLM_SINGLE_MODEL"] = "1"
    import config as _cfg
    _cfg.LLM_SINGLE_MODEL = True

    # Una run que revienta (cuota, 5xx sostenidos, bug del harness) no debe tirar
    # la batería entera: se registra con best=None y se sigue con la siguiente.
    try:
        a = run_single(arch, task, turns=6, max_cost=2.0, verbose=False, quick=False,
                       target_h=int(os.environ.get("TARGET_H", "0")))
    except Exception as e:  # noqa: BLE001 - queremos registrar cualquier fallo
        res = {
            "arch": arch, "task": task, "cond": cond, "rep": rep,
            "run_id": None, "best": None, "baseline": None, "curve": [],
            "turns": 0, "cost": 0.0, "tools": 0,
            "error": f"{type(e).__name__}: {str(e)[:400]}",
        }
        mark.write_text(json.dumps(res, ensure_ascii=False))
        print(f"[error] {arch} {cond} rep{rep} -> {res['error']}", flush=True)
        return res

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
        # modelo/provider RESUELTOS (pueden diferir de los pedidos si hubo
        # fallback en la cadena): sin esto el coste no es interpretable
        "model": getattr(a.llm, "model", None),
        "provider": getattr(a.llm, "provider", None),
    }
    mark.write_text(json.dumps(res, ensure_ascii=False))
    print(f"[done] {arch} {cond} rep{rep} -> {a.run_id} best={res['best']} "
          f"cost=${res['cost']:.3f} tools={n_tools} model={res['model']}", flush=True)
    return res


def preflight(arch: str, task: str, reps: int) -> int:
    """Sondeo L3 ANTES de consumir una batería entera: comprueba credenciales,
    cuota disponible y el tamaño real del prompt con schemas. Devuelve exit code
    (0=listo, 2=no lanzar). Gasta entre 1 y 2 llamadas mínimas — la única pieza
    con coste de tokens de todo el proceso de decisión."""
    from agent.llm import LLM
    from config import PATHS, VISION_PROVIDER
    from tools.domain import build_domain_registry

    print("== PREFLIGHT ==", flush=True)
    llm = LLM(model=None, use_cache=False)
    provider = getattr(llm, "provider", "?")
    print(f"  agente  -> {provider} / {getattr(llm, 'model', '?')}", flush=True)
    print(f"  visión  -> {VISION_PROVIDER or provider} / "
          f"{getattr(llm, '_vision_models', None) or '(mismo que agente)'}", flush=True)

    try:
        resp = llm.generate("Preflight: responde exactamente OK.", temperature=0.0)
        print(f"  sondeo credenciales/cuota: OK in={resp.input_tokens} "
              f"out={resp.output_tokens} -> {resp.text.strip()[:40]!r}", flush=True)
    except Exception as e:
        print(f"  SONDA FALLIDA (no lanzar): {type(e).__name__}: {str(e)[:300]}",
              flush=True)
        print("PREFLIGHT_FAIL", flush=True)
        return 2

    # prompt real del agente: system + estado minimo + TODOS los schemas de tools
    try:
        registry = build_domain_registry(llm, archetype=arch, task=task)
        system = getattr(llm, "_system_prompt", None)
        head = (system() if callable(system) else "") or "Eres un agente de diseño web."
        probe = f"{head}\n\nTarea: {task}\nMejor candidato: H0 total=80.\n" \
                "TURNO ACTUAL: Decide tu próxima acción."
        resp2 = llm.generate(probe, tools=registry.schemas(), temperature=0.0)
        in_tok = getattr(resp2, "input_tokens", 0)
        print(f"  prompt real con schemas: {in_tok} input tokens (compatible y 200 OK)",
              flush=True)
    except Exception as e:
        print(f"  prompt con schemas RECHAZADO: {type(e).__name__}: {str(e)[:300]}",
              flush=True)
        print("  (el sondeo de cuota pasó; el prompt completo puede fallar en la batería)",
              flush=True)
        in_tok = 0

    # limites conocidos por proveedor (TPM) para avisar antes de un muro 413
    known_limits = {"groq": 8000, "gemini": None, "mistral": None,
                    "cerebras": None, "openrouter": None}
    tpm = known_limits.get(provider)
    if tpm and in_tok >= int(0.8 * tpm):
        print(f"  WARN: prompt ({in_tok}) >= 80% del limite TPM de {provider} "
              f"({tpm}): la batería fallará con 413. No lanzar.", flush=True)
        print("PREFLIGHT_FAIL", flush=True)
        return 2

    turns = 6
    out_tok = 2500  # output medio por turno (generacion HTML larga)
    per_run = turns * (max(in_tok, 2000) + out_tok)
    for sel in (6, 4):
        runs = sel * 2
        print(f"  proyeccion n={sel}+{sel} ({runs} runs): ~{per_run * runs:,} "
              f"tokens agente + ~{73 * 1844:,} tokens vision (Qwen/Groq) "
              f"(~${runs * 0.04:.2f} agente si Gemini proyecto; verificado en bateria Mistral)",
              flush=True)
    print("PREFLIGHT_OK Para REP casar tu cuota diaria: si cubre ~2x la "
          "proyeccion de n=6, lanza REPS=6; si estas justo, REPS=4.", flush=True)
    return 0


def _write_summary(results: list[dict], paused: bool = False,
                   note: str | None = None) -> None:
    """Resumen de la batería con la integridad auditable (modelo resuelto único).
    Se escribe TAMBIÉN al pausar por cuota, para que la batería sea resumible y
    el estado sea inspeccionable sin esperar a completar las REPS."""
    used = sorted({(r.get("provider") or "?", r.get("model") or "?") for r in results})
    failed = [f"{r['cond']}/rep{r['rep']}" for r in results
              if r.get("best") is None or r.get("error")]
    summary = {
        "results": results,
        "resolved_models": [list(u) for u in used],
        "failed_runs": failed,
        "valid": len(used) == 1 and not failed and not paused,
        "paused": paused,
        "note": note,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if len(used) != 1:
        print(f"[WARN] modelos resueltos distintos en la bateria: {used} "
              f"-> NO comparable, revisar markers antes de analizar", flush=True)
    if failed:
        print(f"[WARN] runs sin score valido: {failed} -> NO usar en estadistica",
              flush=True)


if __name__ == "__main__":
    reps = int(os.environ.get("REPS", "2"))
    arch_env = os.environ.get("ARCH")
    archs = [(a, t) for a, t in TASKS if not arch_env or a == arch_env]
    if os.environ.get("PREFLIGHT", "0") not in ("0", ""):
        arch, task = archs[0]
        sys.exit(preflight(arch, task, reps))
    results = []
    consecutive_quota_failures = 0
    for arch, task in archs:
        for rep in range(1, reps + 1):
            for cond in ("on", "off"):
                res = run_one(arch, task, cond, rep)
                results.append(res)
                if res.get("error") and _is_quota_error(res["error"]):
                    consecutive_quota_failures += 1
                    # Si la cuota muere a mitad (solía girar 1.5h en 429 sin
                    # dejar resumen), pausamos LIMPIO: los markers ya escritos
                    # permiten retomar la batería otro día (run_one hace skip).
                    if consecutive_quota_failures >= 2:
                        done = len(results)
                        total = len(archs) * reps * 2
                        note = (f"cuota del proveedor agotada tras {done}/{total} "
                                "runs; batería PAUSADA. Retomar con el mismo "
                                "comando (mismo REPS y providers): los markers "
                                "hechos se saltan y se continúa.")
                        print(f"BATTERY_PAUSED {done}/{total} runs — {note}",
                              flush=True)
                        _write_summary(results, paused=True, note=note)
                        sys.exit(3)
                else:
                    consecutive_quota_failures = 0

    _write_summary(results)
    print("BATTERY_COMPLETE", flush=True)