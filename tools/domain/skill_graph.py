"""Grafo de dependencias de capacidades ejecutables (Punto 12 — Graph
Engineering, Feng et al. 2026, "Graph Engineering in the Era of LLM Agents:
From Individual Intelligence to System Intelligence", §3.3 Skill Composition
y §5.1 Graph-Native Capability Substrates).

Adaptación de "Graph of Skills" (Li et al., 2026) y "SkillDAG": las
capacidades ejecutables del harness (tools) son nodos tipados y las aristas
codifican relaciones operativas:

  depends_on   : B requiere que A se haya ejecutado antes en la run para que
                 su señal tenga sentido (prerequisito duro).
  inhibits     : A y B compiten por la misma señal/presupuesto; ejecutar ambos
                 en una run desperdicia turnos (sin aristas activas hoy: los
                 críticos VLM se hicieron deliberadamente complementarios).
  repeat_guard : llamar B dos veces sin un generate_candidate intermedio
                 repite el mismo juicio sobre el mismo candidato (el bypass de
                 caché de los críticos visuales, F1 del Punto 11, hace que cada
                 llamada cueste tokens reales).

El bloque derivado se inyecta en el estado del agente como advertencias
dinámicas: violaciones observadas hasta el turno actual (deps_warnings, reactiva)
+ prerequisitos pendientes de tools no ejecutadas (deps_pending, predictiva,
Punto 12b) + resumen de aristas.
Es conocimiento declarativo en domain/generated/skill_deps.yaml, editable vía
meta-evolución (edit_skill pasa por el acceptance gate).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from config import PATHS

DEPS_FILE = Path("generated") / "skill_deps.yaml"
MUTATOR_TOOL = "generate_candidate"


def load_deps() -> dict:
    """Carga el grafo declarativo. {} si falta o es inválido (nunca rompe)."""
    f = PATHS["domain"] / DEPS_FILE
    if not f.exists():
        return {}
    try:
        data = yaml.safe_load(f.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def deps_warnings(executed: list[str]) -> list[str]:
    """Violaciones del grafo observadas en la secuencia de tools ya ejecutadas
    (en orden). La secuencia se conserva íntegra para el repeat_guard; las
    comprobaciones de pertenencia usan el conjunto deduplicado."""
    deps = load_deps()
    seq = [t for t in executed if t]
    seen = set(seq)
    warns: list[str] = []

    def _pos(tool: str) -> list[int]:
        return [i for i, t in enumerate(seq) if t == tool]

    for tool, spec in deps.items():
        if not isinstance(spec, dict):
            continue
        # depends_on: prerequisito ausente => señal posiblemente inválida
        for pre in spec.get("depends_on") or []:
            if tool in seen and pre not in seen:
                warns.append(
                    f"`{tool}` se ejecutó sin su prerequisito `{pre}`: su "
                    "resultado puede no tener sentido. Ejecuta el prerequisito "
                    "antes de interpretar/usar esa señal."
                )
        # inhibits: ambas compiten; si coexisten en la run, avisar una vez
        for other in spec.get("inhibits") or []:
            pair = sorted((tool, other))
            if tool in seen and other in seen and \
               f"{pair[0]}+{pair[1]} compiten" not in " ".join(warns):
                warns.append(
                    f"`{tool}` y `{other}` compiten por la misma señal: no "
                    "aportan valor conjunto en la misma run."
                )
        # repeat_guard: segunda llamada sin mutación intermedia = juicio repetido
        if spec.get("repeat_guard"):
            calls = _pos(tool)
            for prev_i, cur_i in zip(calls, calls[1:]):
                between = seq[prev_i + 1:cur_i]
                if MUTATOR_TOOL not in between:
                    warns.append(
                        f"`{tool}` repetido sin `{MUTATOR_TOOL}` intermedio: "
                        "criticarías el mismo candidato con el mismo juicio. "
                        f"Llama a `{MUTATOR_TOOL}` antes de volver a criticar."
                    )
                    break
    return warns[:5]


def deps_pending(executed: list[str]) -> list[str]:
    """Versión predictiva (Punto 12b): herramientas no ejecutadas cuyo
    prerequisito tampoco está ejecutado. Avisa ANTES de que el agente intente
    llamarlas, evitando la violación reactiva de deps_warnings()."""
    deps = load_deps()
    seen = set(executed)
    pending: list[str] = []

    for tool, spec in deps.items():
        if tool in seen:
            continue  # ya ejecutada — no hay nada pendiente
        if not isinstance(spec, dict):
            continue
        pres = spec.get("depends_on") or []
        missing = [p for p in pres if p not in seen]
        if missing:
            pending.append(
                f"`{tool}` no ejecutado — requiere previamente "
                + ", ".join(f"`{p}`" for p in missing)
                + ". Ejecuta primero el prerequisito."
            )
    return pending[:5]


def deps_edges_summary() -> list[str]:
    """Resumen compacto de las aristas del grafo (para el estado del agente)."""
    lines = []
    for tool, spec in sorted(load_deps().items()):
        if not isinstance(spec, dict):
            continue
        parts = []
        pres = spec.get("depends_on") or []
        if pres:
            parts.append("requiere " + ", ".join(f"`{p}`" for p in pres))
        if spec.get("repeat_guard"):
            parts.append(f"no repetir sin `{MUTATOR_TOOL}` intermedio")
        if parts:
            lines.append(f"- `{tool}`: " + "; ".join(parts))
    return lines


def deps_block(executed: list[str]) -> str:
    """Bloque completo para el estado del agente: violaciones reactivas +
    prerequisitos pendientes (predictivo) + aristas del grafo. Cadena vacía
    si no hay grafo, violaciones ni pendientes."""
    warns = deps_warnings(executed)
    pending = deps_pending(executed)
    edges = deps_edges_summary()
    if not warns and not pending and not edges:
        return ""
    out = []
    if warns:
        out.append("VIOLACIONES DETECTADAS en esta run:")
        out.extend(f"- {w}" for w in warns)
    if pending:
        out.append("PASOS PENDIENTES (prerequisitos no ejecutados aún):")
        out.extend(f"- {p}" for p in pending)
    if edges:
        out.append("Aristas activas:")
        out.extend(edges)
    return "\n".join(out)
