"""Semilla del dominio desde Docs/.

Convierte Docs/Archetypes/* y Docs/global_* a domain/ (YAML, JSON) consumible
por el agente y editable por meta-evolución.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

DOCS = Path(__file__).resolve().parent.parent.parent / "Docs"
DOMAIN = Path(__file__).resolve().parent.parent / "domain"

ARCHETYPE_MAP = {
    "landing page": "landing-page",
    "corporate-business": "corporate-business",
    "e-commerce": "ecommerce",
    "saas-dashboard": "saas-dashboard",
    "portfolio-creative": "portfolio-creative",
    "blog-content": "blog-content",
}


def _md_to_yaml(md_text: str) -> dict:
    """Convierte markdown estructurado a un dict YAML simple (sectiones → listas)."""
    result: dict = {}
    current_key = None
    lines = md_text.splitlines()
    i = 0
    last_keyword = None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") and not s.startswith("## ") and not s.startswith("### "):
            # headers con # puro = comentarios
            if s.startswith("# ") and s[2:]:
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


def seed_global(archetype_dir_ignored: bool = True) -> None:
    """Copia global_rules, agent_skills y global_workflows a domain/."""
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


def seed_archetypes() -> None:
    for folder, slug in ARCHETYPE_MAP.items():
        src_dir = DOCS / "Archetypes" / folder
        dst_dir = DOMAIN / "archetypes" / slug
        if not src_dir.exists():
            print(f"[warn] falta {src_dir}")
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)

        # rules.md -> rules.yaml
        rules_md = src_dir / "project-rules.md"
        if rules_md.exists():
            with open(dst_dir / "rules.yaml", "w") as f:
                yaml.dump(_md_to_yaml(rules_md.read_text()), f, allow_unicode=True, sort_keys=False)
            print(f"[seed] {slug}/rules.yaml")

        # workflows.md -> workflow.yaml
        wf_md = src_dir / "project-workflows.md"
        if wf_md.exists():
            with open(dst_dir / "workflow.yaml", "w") as f:
                yaml.dump(_md_to_yaml(wf_md.read_text()), f, allow_unicode=True, sort_keys=False)
            print(f"[seed] {slug}/workflow.yaml")

        # tech-stack.json -> stack.json
        stack_json = src_dir / "tech-stack.json"
        if stack_json.exists():
            data = json.loads(stack_json.read_text())
            with open(dst_dir / "stack.json", "w") as f:
                json.dump(data, f, indent=2)
            print(f"[seed] {slug}/stack.json")

        # context.md -> archetype.yaml
        ctx_md = src_dir / "project-context.md"
        if ctx_md.exists():
            with open(dst_dir / "archetype.yaml", "w") as f:
                yaml.dump(_md_to_yaml(ctx_md.read_text()), f, allow_unicode=True, sort_keys=False)
            print(f"[seed] {slug}/archetype.yaml")


def main() -> None:
    DOMAIN.mkdir(parents=True, exist_ok=True)
    seed_global()
    seed_archetypes()
    print("Seed completado en", DOMAIN)


if __name__ == "__main__":
    main()