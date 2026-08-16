"""META-EVOLUCIÓN: el agente puede editar su propio harness (reglas, skills,
workflows en domain/).

F1: las ediciones NO se aplican al instante: `edit_skill` registra una PROPUESTA
en la tabla `harness_edits` (decisión=pending) y deja el cambio en staging bajo
domain/.proposals/. El gate (`scripts/gate_harness_edit.py`) decide con train/dev
si la propuesta se promueve (aplica el cambio a domain/) o se rechaza (rollback).

F2: cada edición declara el COMPONENTE funcional del harness que toca (mapa
HARNESS_COMPONENTS). El path debe pertenecer a ese componente; una edición por
componente, para mantener crédito atribuible de las ganancias.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from agent.memory_db import MemoryDB
from config import HARNESS_COMPONENTS, PATHS
from tools.base import Tool


def resolve_component(path: str) -> str | None:
    """Devuelve el componente al que pertenece un path relativo a domain/."""
    clean = path.replace("\\", "/").lstrip("/")
    first = clean.split("/", 1)[0] if clean else ""
    for component, prefixes in HARNESS_COMPONENTS.items():
        if first in prefixes:
            return component
    return None


class EditSkill(Tool):
    name = "edit_skill"
    description = (
        "Propone una edición del harness en domain/ (reglas, skills, workflows, "
        "arquetipos). NO se aplica al instante: queda como propuesta pending y "
        "un acceptance gate con train/dev decide si se promueve o se revierte. "
        "Cada edición declara UN componente del harness (context_memory | "
        "tools_specs) y el path debe pertenecer a ese componente. Núcleo de la "
        "meta-evolución acotada."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "Componente del harness a editar: context_memory (generated/) | tools_specs (archetypes/)",
                    },
                    "path": {
                        "type": "string",
                        "description": "Ruta bajo domain/ (ej: archetypes/landing-page/rules.yaml)",
                    },
                    "instruction": {
                        "type": "string",
                        "description": "Qué cambio aplicar (puede ser reemplazo directo de YAML o instrucción)",
                    },
                    "mode": {
                        "type": "string",
                        "description": "replace (reemplaza el archivo) | append (añade una sección)",
                    },
                },
                "required": ["component", "path", "instruction"],
            },
        }

    def run(self, component: str = "", path: str = "", instruction: str = "",
            mode: str = "replace", **kwargs) -> str:
        comp = resolve_component(path)
        if comp is None:
            return f"ERROR: '{path}' no pertenece a ningún componente editable (generated/ o archetypes/)."
        if comp != component:
            return f"ERROR: componente '{component}' no coincide con el path '{path}' (pertenece a '{comp}')."

        target = (PATHS["domain"] / path).resolve()
        if not str(target).startswith(str(PATHS["domain"].resolve())):
            return "ERROR: path fuera de domain/"
        target.parent.mkdir(parents=True, exist_ok=True)
        before = target.read_text() if target.exists() else ""

        # Calcular el contenido AFTER (según mode), validando YAML.
        if mode == "append":
            after = before + ("\n" if before and not before.endswith("\n") else "") + instruction + "\n"
        else:
            try:
                parsed = yaml.safe_load(instruction)
                if not isinstance(parsed, dict):
                    return f"ERROR: instruction no es YAML dict válido: {parsed}"
                after = instruction
            except yaml.YAMLError as e:
                return f"ERROR: YAML inválido: {e}"
        try:
            yaml.safe_load(after)
        except yaml.YAMLError as e:
            return f"ERROR: el YAML resultante es inválido: {e}"

        run_id = kwargs.get("run_id") or "global"
        proposal_id = f"{datetime.now().strftime('%Y%m%dT%H%M%S%f')}"

        # staging: no se toca domain/ vivo; el cambio queda listo para el gate.
        staged = (PATHS["domain"] / ".proposals" / proposal_id / path)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(after)

        db = MemoryDB()
        try:
            db.add_harness_edit(
                proposal_id=proposal_id,
                run_id=run_id,
                component=comp,
                file=path,
                before=before,
                after=after,
                mode=mode,
                plan=instruction[:500],
            )
        finally:
            db.close()

        return (
            f"OK: propuesta {proposal_id} registrada (pending). No se ha aplicado a domain/ todavía. "
            f"El acceptance gate la evaluará en train/dev; si se aprueba, se promueve; si no, se descarta. "
            f"Componente: {comp} · archivo: {path}."
        )


class ReviewHarness(Tool):
    name = "review_harness"
    description = (
        "Lista los archivos del harness en domain/ agrupados por componente "
        "funcional (context_memory: generated/ · tools_specs: archetypes/) para "
        "decidir dónde proponer una mejora."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Subruta bajo domain/ (opcional)"},
                },
            },
        }

    def run(self, path: str = "", **kwargs) -> str:
        base = PATHS["domain"] / path if path else PATHS["domain"]
        groups: dict[str, list[str]] = {}
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in (".yaml", ".yml", ".json", ".md"):
                rel = str(p.relative_to(PATHS["domain"]))
                if ".proposals" in rel:
                    continue
                comp = resolve_component(rel) or "otros"
                groups.setdefault(comp, []).append(f"{rel}  ({p.stat().st_size}B)")
        lines = []
        for comp in sorted(groups):
            lines.append(f"[{comp}]")
            lines.extend("  " + l for l in groups[comp])
        return "\n".join(lines[:100]) or "(vacío)"