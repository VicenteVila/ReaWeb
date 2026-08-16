"""Semilla del dominio desde Docs/.

Convierte Docs/global_* (reglas globales, skills, workflows) a domain/generated
(YAML) consumible por el agente y editable por meta-evolución.

Los arquetipos NO se regeneran desde Docs/: su conocimiento vive solo en
domain/archetypes/* (fuente de verdad viva, mejorada por meta-evolución).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

DOCS = Path(__file__).resolve().parent.parent / "Docs"
DOMAIN = Path(__file__).resolve().parent.parent / "domain"


def _md_to_yaml(md_text: str) -> dict:
    """Convierte markdown estructurado a un dict YAML simple (sectiones → listas)."""
    result: dict = {}
    current_key = None
    for line in md_text.splitlines():
        s = line.strip()
        if not s:
            continue
        # Headers con # puro = comentarios (se ignoran)
        if s.startswith("# ") and not s.startswith("## ") and not s.startswith("### "):
            continue
        # Detectar heads de nivel 2/3 que actúan como claves
        if s.startswith("## "):
            current_key = s[3:].strip().lower().replace(" ", "_").replace("/", "").strip("_")
            if current_key and not current_key.startswith("#"):
                result[current_key] = []
            else:
                current_key = None
            continue
        if s.startswith("### "):
            current_key = s[4:].strip().lower().replace(" ", "_")
            if current_key:
                result[current_key] = []
            continue
        if current_key:
            if isinstance(result.get(current_key), list):
                result[current_key].append(s)
    return result


def seed_global() -> None:
    """Copia global_rules, agent_skills y global_workflows a domain/generated."""
    global_map = {
        "global_rules.md": "global_rules.yaml",
        "agent_skills.md": "skills.yaml",
        "global_workflows.md": "workflows.yaml",
    }
    for src, dst in global_map.items():
        p = DOCS / src
        if not p.exists():
            continue
        data = _md_to_yaml(p.read_text())
        (DOMAIN / "generated").mkdir(parents=True, exist_ok=True)
        with open(DOMAIN / "generated" / dst, "w") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        print(f"[seed] {dst} ({len(data)} secciones)")


def main() -> None:
    DOMAIN.mkdir(parents=True, exist_ok=True)
    seed_global()
    print("Seed completado en", DOMAIN / "generated")


if __name__ == "__main__":
    main()