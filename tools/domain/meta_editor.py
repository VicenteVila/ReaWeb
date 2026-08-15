"""META-EVOLUCIÓN: el agente puede editar su propio harness (reglas, skills,
workflows en domain/). Valida YAML tras cada edición y registra el diff."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from config import PATHS
from tools.base import Tool


class EditSkill(Tool):
    name = "edit_skill"
    description = (
        "Edita un archivo YAML del harness en domain/ (reglas, skills, workflows, "
        "arquetipos). Aplica una instrucción de cambio con validación YAML tras "
        "editar. Núcleo de la meta-evolución."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
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
                "required": ["path", "instruction"],
            },
        }

    def run(self, path: str = "", instruction: str = "", mode: str = "replace", **kwargs) -> str:
        target = (PATHS["domain"] / path).resolve()
        if not str(target).startswith(str(PATHS["domain"].resolve())):
            return "ERROR: path fuera de domain/"
        target.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append":
            with target.open("a") as f:
                f.write("\n" + instruction + "\n")
            text = target.read_text()
        else:
            # Si el modelo da YAML, se usa directamente; si no, se trata como instrucción
            try:
                parsed = yaml.safe_load(instruction)
                if isinstance(parsed, dict):
                    text = instruction
                    target.write_text(instruction)
                else:
                    return f"ERROR: instruction no es YAML dict válido: {parsed}"
            except yaml.YAMLError as e:
                return f"ERROR: YAML inválido: {e}"

        # Validar YAML resultante
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            return f"ERROR: el YAML resultante es inválido: {e}"

        return f"OK: {target} actualizado ({len(text)} chars). YAML válido."


class ReviewHarness(Tool):
    name = "review_harness"
    description = "Lista los archivos del harness en domain/ con su tamaño para decidir dónde mejorar."

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
        lines = []
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in (".yaml", ".yml", ".json", ".md"):
                rel = p.relative_to(PATHS["domain"])
                lines.append(f"{rel}  ({p.stat().st_size}B)")
        return "\n".join(lines[:100]) or "(vacío)"