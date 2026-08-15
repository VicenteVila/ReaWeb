"""Tool fetch_repo_topics: clasifica las categorías sujet de arXiv (cs.*) por repo
a partir del README de cada repositorio y genera graph_data.json con los datos del
grafo de conocimientos.

Flujo:
  1. Descarga el README.md de cada repo (reutiliza readme_fetcher._http_get/_download).
  2. Con el LLM, clasifica el repo en categorías sujet arXiv (code + descripción corta).
  3. Escribe workspace/current/graph_data.json:
       {
         "root": {"name": "Vicente Vila", "email": "vicentevilaramirez@gmail.com"},
         "repos": [{"name": "TraceForge", "topics": [{"code": "cs.AI", "desc": "..."}]}]
       }
  4. Guarda una copia de trazabilidad en runs/<run_id>/reference/<repo>_topics.json.
"""
from __future__ import annotations

import json

from config import PATHS
from tools.base import Tool
from tools.domain.readme_fetcher import _download_readme, parse_github_repos

ARXIV_SUBJECTS = (
    "cs.AI, cs.LG, cs.CL, cs.CV, cs.MA, cs.SE, cs.SY, cs.NE, cs.IR, cs.DB, "
    "cs.CR, cs.HC, cs.RO, cs.LO, cs.DC, cs.DS"
)

CLASSIFY_PROMPT = """Eres un investigador que clasifica repositorios según las categorías sujet de arXiv.

El repositorio "{repo}" tiene este README:

---
{readme_snippet}
---

Tarea: determina en qué temas de Inteligencia Artificial se trabaja en este repositorio.
Elige SOLO categorías sujet de arXiv entre estas: {subjects}.

Devuelve EXCLUSIVAMENTE un JSON válido con este esquema (sin markdown, sin texto extra):
{{
  "topics": [
    {{"code": "cs.AI", "desc": "Descripción en español, 1 frase corta, qué se trabaja aquí"}}
  ]
}}

Reglas:
- Máximo 4 categorías, mínimo 1. Solo si el README realmente sustenta la categoría.
- Si el README es muy corto o genérico, usa solo las categorías más evidentes (p. ej. cs.AI).
- No inventes categorías que el README no sustente.
"""


class FetchRepoTopics(Tool):
    name = "fetch_repo_topics"
    description = (
        "Clasifica las categorías sujet de arXiv (cs.AI, cs.LG, cs.CL, cs.MA...) de "
        "cada repositorio de github.com/VicenteVila descargando su README y analizándolo "
        "con el LLM. Genera workspace/current/graph_data.json con el nodo raíz "
        "(Vicente Vila + email) y los topics por repo, listo para embeker en el grafo "
        "de conocimientos. Devuelve el resumen de repos y categorías."
    )

    def __init__(self, llm=None, task: str = ""):
        self.llm = llm
        self.task = task
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Propietario de GitHub (default VicenteVila)"},
                    "root_name": {"type": "string", "description": "Nombre del nodo raíz (default 'Vicente Vila')"},
                    "root_email": {"type": "string", "description": "Email del nodo raíz"},
                    "repos": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Repos explícitos (si se omite, se parsean de la tarea)",
                    },
                },
            },
        }

    def run(self, owner: str = "VicenteVila", root_name: str = "Vicente Vila",
            root_email: str = "vicentevilaramirez@gmail.com",
            repos: list[str] | None = None, **kwargs) -> str:
        if repos is None:
            repos = parse_github_repos(self.task, owner)
        if not repos:
            return ("ERROR: no se encontraron repos github.com/VicenteVila/<repo> "
                    "en la tarea ni en el argumento repos.")

        graph = {
            "root": {"name": root_name, "email": root_email},
            "repos": [],
        }
        errors = []
        run_id = kwargs.get("run_id")
        ref_dir = PATHS["runs"] / run_id / "reference" if run_id else None

        for repo in repos:
            topics = self._classify_repo(owner, repo, ref_dir)
            if topics is None:
                errors.append(repo)
                continue
            graph["repos"].append({"name": repo, "topics": topics})

        if not graph["repos"]:
            return "ERROR: no se pudo clasificar ningún repo. Fallos: " + "; ".join(errors)

        out_file = PATHS["current"] / "graph_data.json"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(graph, ensure_ascii=False, indent=2))

        if ref_dir:
            ref_dir.mkdir(parents=True, exist_ok=True)
            (ref_dir / "graph_data.json").write_text(
                json.dumps(graph, ensure_ascii=False, indent=2)
            )

        lines = [f"OK: {out_file} generado con {len(graph['repos'])} repos:"]
        for r in graph["repos"]:
            codes = ", ".join(t["code"] for t in r["topics"])
            lines.append(f"- {r['name']}: {codes}")
        if errors:
            lines.append("Sin clasificar: " + ", ".join(errors))
        lines.append(
            "\nUsa estos datos para construir el grafo SVG: el nodo raíz (nombre + email) "
            "y un nodo por repo; al hacer hover sobre un repo, muestra sus categorías "
            "arXiv y el enlace a repos/<repo>/index.html."
        )
        return "\n".join(lines)

    def _classify_repo(self, owner: str, repo: str, ref_dir) -> list[dict] | None:
        md, err = _download_readme(owner, repo)
        if err:
            return None
        snippet = md[:3000]
        prompt = CLASSIFY_PROMPT.format(
            repo=repo, readme_snippet=snippet, subjects=ARXIV_SUBJECTS
        )
        try:
            out = self.llm.generate(prompt, temperature=0.2)
            raw = out.text
        except Exception as e:  # noqa: BLE001
            raw = getattr(e, "response", "") or ""
        topics = self._parse_topics(raw)
        if topics is None:
            return None
        if ref_dir:
            ref_dir.mkdir(parents=True, exist_ok=True)
            (ref_dir / f"{repo}_topics.json").write_text(
                json.dumps(topics, ensure_ascii=False, indent=2)
            )
        return topics

    def _parse_topics(self, raw: str) -> list[dict] | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1:
                return None
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        topics = data.get("topics") if isinstance(data, dict) else data
        if not isinstance(topics, list):
            return None
        clean = []
        for t in topics:
            if not isinstance(t, dict):
                continue
            code = str(t.get("code", "")).strip()
            desc = str(t.get("desc", "")).strip()
            if code and code.startswith("cs."):
                clean.append({"code": code, "desc": desc or code})
        return clean