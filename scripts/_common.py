"""Lógica compartida para ejecutar runs desde los entrypoints (run_agent, run_battery)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.agent import Agent
from agent.llm import LLM
from tools import registry as base_registry
from tools.domain import build_domain_registry
from config import ensure_dirs, PATHS


def load_archetype(archetype: str) -> str:
    """Carga rules.yaml + tech-stack del arquetipo (si existen)."""
    base = PATHS["domain"] / "archetypes" / archetype
    parts = []
    rules_file = base / "rules.yaml"
    if rules_file.exists():
        parts.append(rules_file.read_text())
    stack_file = base / "tech-stack.json"
    if stack_file.exists():
        parts.append("--- STACK ---\n" + stack_file.read_text()[:2000])
    return "\n".join(parts)


def build_agent(archetype: str, task: str, model: str | None, turns: int,
                max_cost: float, allow_meta: bool, verbose: bool) -> tuple[Agent, object]:
    """Construye el agente + registry listos para ejecutar una run."""
    ensure_dirs()
    llm = LLM(model=model)
    rules = load_archetype(archetype)

    arq_dir = PATHS["domain"] / "archetypes" / archetype
    if not arq_dir.exists():
        print(f"[WARN] Arquetipo '{archetype}' no existe en domain/archetypes/. Continuo con contexto genérico.", file=sys.stderr)

    agent = Agent(
        llm=llm,
        archetype_name=archetype,
        task=task,
        rules=rules,
        stack=rules,
        max_turns=turns,
        max_cost_usd=max_cost,
        allow_meta_edits=allow_meta,
        verbose=verbose,
    )

    registry = build_domain_registry(
        llm,
        archetype=archetype,
        task=task,
        rules=rules,
        stack=rules,
    )
    for tool_name in ("read_file", "write_file", "edit_file", "list_files", "python_exec", "bash"):
        try:
            registry._tools[tool_name] = base_registry.get(tool_name)
        except KeyError:
            pass
    return agent, registry


def run_single(archetype: str, task: str, model: str | None = None,
               turns: int = 20, max_cost: float = 5.0,
               allow_meta: bool = True, verbose: bool = True) -> Agent:
    """Ejecuta una run completa y devuelve el agente (con run_dir resuelto)."""
    agent, registry = build_agent(
        archetype, task, model, turns, max_cost, allow_meta, verbose
    )
    final = agent.run(registry)
    if verbose:
        print("\n" + "=" * 60)
        print(final)
    return agent