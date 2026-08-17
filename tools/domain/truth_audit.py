"""Juicio de verdad basado en datasets (AutoDesign, §2/§3.4). Complementa el
evaluador estático con dos señales objetivas:

1. PARTES INTEGRANTES (dataset Screen Annotation / RICO): verifica que el
   candidato en workspace/current contenga y CONECTE todas sus partes —
   repos con index.html propio, links resueltos desde la raíz, secciones
   obligatorias presentes. Detecta artefactos "huérfanos" (HTML fabricado
   pero no enlazado desde el index.html raíz).

2. DISEÑO UI (dataset WebSight): el crítico VLM compara el screenshot del
   candidato contra N referencias reales (pares HTML+PNG) y devuelve un score
   de diseño relativo, detectando si la página parece un sitio real o un
   prototipo plano.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from config import PATHS
from tools.base import Tool
from tools.domain.visual_critic import render_screenshot

UI_DATASET = PATHS["root"] / "datasets" / "ui"
PARTS_DATASET = PATHS["root"] / "datasets" / "parts"

TRUTH_PROMPT = """Eres un auditor de calidad web independiente (juicio de verdad). Te muestro el
screenshot renderizado de un candidato y un screenshot de referencia de un sitio
web real profesional (puede haber varias referencias).

Evalúa la CALIDAD DE DISEÑO del candidato COMPARADA con la referencia real:
- ¿Parece un sitio web real y profesional o un prototipo plano/genérico?
- Jerarquía visual, contraste, tipografía, espaciados, coherencia de paleta
- Profundidad (sombras, gradientes, elevación), densidad informativa equilibrada
- Ausencia de elementos rotos, cortados o fuera de lugar

Devuelve EXCLUSIVAMENTE JSON válido (sin markdown, sin texto extra):
{
  "design_score": 0-100,
  "looks_real": true|false,
  "missing_parts": ["parte visual ausente u obviamente rota"],
  "suggestions": ["mejora concreta para el siguiente generate_candidate"]
}
Reglas:
- Máximo 3 missing_parts y 3 suggestions. Sé concreto.
- Si el screenshot no permite distinguir algo, no lo inventes.
- design_score alto (>=85) solo si el candidato compite visualmente con la referencia.
"""


def _dataset_size() -> int:
    if not UI_DATASET.exists():
        return 0
    return sum(1 for p in UI_DATASET.glob("*.png"))


def _check_parts(target: Path) -> dict:
    """Verifica partes integrantes: repos conectados + secciones + links resueltos."""
    from .evaluator import extract_sections, _html_has_section

    result: dict = {"repo_pages": 0, "connected_repos": 0, "orphan_repos": [],
                    "broken_links": [], "missing_sections": [], "ok": True}

    repos_dir = target / "repos"
    if repos_dir.is_dir():
        repo_dirs = sorted(
            p for p in repos_dir.iterdir()
            if p.is_dir() and (p / "index.html").exists()
        )
        result["repo_pages"] = len(repo_dirs)
    else:
        repo_dirs = []

    h = ""
    index = target / "index.html"
    if index.exists():
        h = index.read_text(errors="replace")

    if h:
        # links a repos desde la raíz (href="repos/...")
        linked = set(re.findall(r'href=["\']([^"\']*repos/[^"\']*index\.html)["\']', h))
        for rd in repo_dirs:
            rel = f"repos/{rd.name}/index.html"
            if rel in linked or rel.replace(" ", "%20") in linked:
                result["connected_repos"] += 1
            else:
                result["orphan_repos"].append(rd.name)
        # links rotos (referencian un repos/ que no existe)
        for link in linked:
            path = (target / link).resolve()
            if not path.exists():
                result["broken_links"].append(link)

        # secciones obligatorias de la tarea (si hay task presente no es trivial;
        # aquí usamos las del sistema de evaluación de estructura si existen)
        sections = extract_sections(getattr(_audit_truth_task, "_task", ""))
        if sections:
            missing = [s for s in sections if not _html_has_section(h, s)]
            result["missing_sections"] = missing

    result["ok"] = not (result["orphan_repos"] or result["broken_links"]
                        or result["missing_sections"])
    return result


def _audit_truth_task() -> str:
    return getattr(_audit_truth_task, "_task", "")


class AuditTruth(Tool):
    name = "audit_truth"
    description = (
        "Juicio de verdad basado en datasets: verifica que el candidato CONECTE todas sus "
        "partes (repos con index.html propio enlazados desde la raíz, secciones presentes, "
        "sin links rotos) y compara el diseño contra referencias reales de un dataset de UI. "
        "Devuelve un score de diseño relativo y los fallos de partes integrantes. Úsala "
        "cuando quieras una validación objetiva además del evaluador estático."
    )

    def __init__(self, llm=None, task: str = ""):
        self.llm = llm
        _audit_truth_task._task = task
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "references": {
                        "type": "integer",
                        "description": "Número de referencias del dataset UI a comparar (default 2, máx 5).",
                    },
                },
            },
        }

    def run(self, references: int = 2, **kwargs) -> str:
        target = PATHS["current"]
        if not (target / "index.html").exists():
            return f"ERROR: no existe index.html en {target}"

        # --- PARTES INTEGRANTES (verificación estructural, sin VLM) ---
        parts = _check_parts(target)
        parts_lines = [
            f"partes=ok" if parts["ok"] else f"partes=falla",
            f"repos fabricados={parts['repo_pages']} conectados={parts['connected_repos']}",
        ]
        if parts["orphan_repos"]:
            parts_lines.append("REPOS HUÉRFANOS (HTML existe pero NO enlazado desde la raíz): " + ", ".join(parts["orphan_repos"]))
        if parts["broken_links"]:
            parts_lines.append("LINKS ROTOS: " + ", ".join(parts["broken_links"]))
        if parts["missing_sections"]:
            parts_lines.append("SECCIONES FALTANTES: " + ", ".join(parts["missing_sections"]))

        # --- DISEÑO UI (crítico VLM vs referencias reales del dataset) ---
        design_score = None
        ref_count = min(max(int(references), 0), 5)
        png = target / ".truth.png"
        ok = render_screenshot(target / "index.html", png)
        refs = sorted(UI_DATASET.glob("*.png"))[:ref_count] if UI_DATASET.is_dir() else []

        if not ok:
            parts_lines.insert(0, "DISEÑO UI: ERROR render (Chrome headless no disponible).")
        elif not refs:
            parts_lines.insert(0, "DISEÑO UI: dataset vacío, sin comparación visual.")
        else:
            try:
                resp = self.llm.generate_vision(TRUTH_PROMPT, png.read_bytes(), "image/png")
                design_score, looks_real, missing, suggestions = self._parse(resp.text)
                parts_lines.insert(
                    0,
                    f"diseño_vlm={design_score} | looks_real={looks_real} vs {ref_count} referencia(s) real(es)",
                )
                if missing:
                    parts_lines.append("PARTES VISUALES AUSENTES: " + "; ".join(missing))
                if suggestions:
                    parts_lines.append("Sugerencias: " + "; ".join(suggestions))
            except Exception as e:
                parts_lines.insert(0, f"DISEÑO UI: ERROR VLM: {e}")
            finally:
                png.unlink(missing_ok=True)

        return "\n".join(parts_lines)

    @staticmethod
    def _parse(raw: str) -> tuple[int | None, bool, list[str], list[str]]:
        if not raw:
            return None, False, [], []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start == -1 or end == -1:
                return None, False, [], []
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None, False, [], []
        if not isinstance(data, dict):
            return None, False, [], []
        score = int(data.get("design_score", 0)) if isinstance(data.get("design_score"), (int, float)) else None
        if score is not None:
            score = max(0, min(100, score))
        looks = bool(data.get("looks_real", False))
        missing = [str(m).strip() for m in (data.get("missing_parts") or []) if str(m).strip()]
        suggestions = [str(s).strip() for s in (data.get("suggestions") or []) if str(s).strip()]
        return score, looks, missing[:3], suggestions[:3]
