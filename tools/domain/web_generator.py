"""Generación de código web. Usa un SUBAGENTE (LLM separado) para producir los
archivos, manteniendo limpio el contexto del agente principal (patrón ReASearch)."""
from __future__ import annotations

import shutil
from pathlib import Path

from config import PATHS
from tools.base import Tool

GENERATOR_PROMPT = """Eres un desarrollador web senior. Genera una página web completa para el siguiente proyecto.

PROYECTO:
{task}

ARQUETIPO: {archetype}
REGLAS DEL ARQUETIPO:
{rules}

STACK PREFERIDO:
{stack}

OBJETIVO DE MEJORA (si existe): {improve}

REQUISITOS VERIFICABLES DE LA TAREA (deben aparecer literalmente en el código,
en index.html o app.js):
{requirements}

REQUISITOS:
1. Una página HTML autocontenida (index.html) con CSS en styles.css y JS en app.js.
2. Diseño responsive (mobile-first), semántico, accesible.
3. Incluye: <!DOCTYPE html>, lang, charset, viewport, title (<60 chars), meta description,
   OG tags, un solo <h1>, alt en imágenes, atributos aria donde haga falta.
4. Las imágenes pueden ser inline SVG o URLs de ejemplo. No uses rutas que no existan.
5. Máximo 1 <style> y 1 <script>; usa defer.
6. Sin console.log. Sin dependencias externas pesadas.

Devuelve EXACTAMENTE 3 bloques separados por la línea ===FILE===
Estructura:
===FILE===
index.html
<contenido del archivo...>
===FILE===
styles.css
<contenido>
===FILE===
app.js
<contenido>
"""


class InspectArchetype(Tool):
    name = "inspect_archetype"
    description = (
        "Carga el conocimiento del arquetipo (reglas, workflows, stack) desde "
        "domain/archetypes/. Úsala para entender qué debe hacer la página antes de generar."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": {}},
        }

    def run(self, **kwargs) -> str:
        from config import PATHS
        import yaml

        base = PATHS["domain"] / "archetypes" / kwargs.get("archetype", "")
        if not base.exists():
            return f"ERROR: arquetipo '{kwargs.get('archetype')}' no encontrado en domain/archetypes/"
        parts = []
        for fname in ("archetype.yaml", "rules.yaml", "workflow.yaml", "stack.json"):
            f = base / fname
            if f.exists():
                parts.append(f"### {fname}\n{f.read_text()}")
        return "\n\n".join(parts)[:8000]


class GenerateCandidate(Tool):
    name = "generate_candidate"
    description = (
        "Genera un candidato web completo (index.html, styles.css, app.js) en "
        "workspace/current usando un subagente LLM. Devuelve las métricas del "
        "objetivo o confirmación."
    )

    def __init__(self, llm, archetype: str = "", task: str = "", rules: str = "", stack: str = "", improve: str = "", requirements: list[str] | None = None):
        self.llm = llm
        self.archetype = archetype
        self.task = task
        self.rules = rules
        self.stack = stack
        self.improve = improve
        from .evaluator import extract_requirements
        self.requirements = requirements if requirements is not None else extract_requirements(task)
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "objective": {
                        "type": "string",
                        "description": "Instrucción objetiva: qué se quiere que esta versión logre (mejora, sección, fix).",
                    },
                },
                "required": ["objective"],
            },
        }

    def run(self, objective: str = "", **kwargs) -> str:
        from .evaluator import evaluate

        prompt = GENERATOR_PROMPT.format(
            task=self.task,
            archetype=self.archetype,
            rules=self.rules[:4000],
            stack=self.stack[:2000],
            improve=objective or self.improve or "Sin mejora específica (versión inicial)",
            requirements="\n".join(f"- {r}" for r in self.requirements) if self.requirements else "(ninguno específico)",
        )
        out = self.llm.generate(prompt, temperature=0.7)
        text = out.text

        files = {}
        blocks = text.split("===FILE===")
        for block in blocks[1:]:
            lines = block.strip("\n").split("\n", 1)
            if len(lines) == 2:
                fname, content = lines[0].strip(), lines[1]
                files[fname] = content

        vuln_files = False
        if not files:
            # Fallback: parsear bloques ```nombre``` si el modelo los usó
            import re
            parts = re.findall(r"```(?:html|css|js)?\s*([\w.]+)\s*\n(.*?)```", text, re.S)
            files = {n: c for n, c in parts}
            vuln_files = True

        if not files or "index.html" not in files:
            return f"ERROR: no se pudo extraer archivos del output del subagente.\n---\n{text[:1500]}"

        target = PATHS["current"]
        target.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            # solo permitir nombres seguros
            if fname.startswith(".") or "/" in fname or "\\" in fname:
                continue
            (target / fname).write_text(content)

        metrics = evaluate(target, requirements=self.requirements)
        task_metrics = f" task={metrics.get('task')}" if metrics.get('task') is not None else ""
        summary = (
            f"Métricas: total={metrics.get('total')} seo={metrics.get('seo')} "
            f"a11y={metrics.get('a11y')} perf={metrics.get('performance')} "
            f"resp={metrics.get('responsive')} bp={metrics.get('best_practices')} "
            f"visual={metrics.get('visual')}{task_metrics}"
        )
        if vuln_files:
            summary += " [PARSEO_FALLBACK]"
        return f"OK: {len(files)} archivos generados. {summary}"


class AuditPage(Tool):
    name = "audit_page"
    description = (
        "Audita el candidato actual en workspace/current con el evaluador ligero. "
        "Devuelve métricas por categoría (incluida 'task', requisitos de la tarea) "
        "y fallos detectados. Ejecuta doble verificación si se pide."
    )

    def __init__(self, requirements: list[str] | None = None):
        from .evaluator import extract_requirements
        self.requirements = requirements or []
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "verify": {
                        "type": "boolean",
                        "description": "Si true, ejecuta la evaluación 2 veces (doble verificación). Por defecto true.",
                    },
                },
            },
        }

    def run(self, verify: bool = True, **kwargs) -> str:
        from .evaluator import evaluate

        target = PATHS["current"]
        if not (target / "index.html").exists():
            return f"ERROR: no existe index.html en {target}"
        m1 = evaluate(target, requirements=self.requirements)
        result = m1.copy()
        if verify:
            m2 = evaluate(target, requirements=self.requirements)
            for k in ("total", "seo", "a11y", "performance", "responsive", "best_practices", "visual", "task"):
                if k in m1 and k in m2 and m1.get(k) is not None and m2.get(k) is not None and abs(m1[k] - m2[k]) > 0:
                    # mantiene el más alto para no penalizar varianza
                    result[k] = max(m1[k], m2[k])
            result["verification"] = "double"
        else:
            result["verification"] = "single"

        fails = result.get("failures", {})
        fail_lines = []
        for cat, lst in fails.items():
            if lst:
                fail_lines.append(f"{cat}: {', '.join(lst)}")
        task_part = f" task={result.get('task')}" if result.get('task') is not None else ""
        res = (
            f"total={result.get('total')} | seo={result.get('seo')} a11y={result.get('a11y')} "
            f"perf={result.get('performance')} resp={result.get('responsive')} "
            f"bp={result.get('best_practices')} visual={result.get('visual')}{task_part} | verificación={result.get('verification')}"
        )
        if fail_lines:
            res += "\nFallos detectados:\n" + "\n".join(fail_lines)
        res += f"\nArchivos: {result.get('files')}"
        return res


class UpdateLessons(Tool):
    name = "update_lessons"
    description = "Escribe una lección (what worked / what didn't / what to try) en lessons.md (incremental y global)."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "worked | didnt | try",
                    },
                    "lesson": {"type": "string", "description": "Texto de la lección"},
                },
                "required": ["category", "lesson"],
            },
        }

    def run(self, category: str = "", lesson: str = "", **kwargs) -> str:
        from agent.memory_db import MemoryDB
        from agent.state import Memory

        run_id = kwargs.get("run_id")
        db = MemoryDB()
        if run_id:
            mem = Memory(run_dir=PATHS["runs"] / run_id, db=db, run_id=run_id)
        else:
            mem = Memory(db=db)
        text = f"## What {category} - {self._now()}\n{lesson}"
        mem.append_incremental(text)
        return f"OK: lección {category} guardada."

    @staticmethod
    def _now():
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


class SelectFinal(Tool):
    name = "select_final"
    description = (
        "Selecciona el candidato final, razonando sobre toda la historia de "
        "optimización (no solo el mejor score). Por defecto copia workspace/current "
        "a runs/ y lo deja exportado."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Razonamiento de la selección final"},
                    "target": {
                        "type": "string",
                        "description": "Nombre del directorio de exportación en runs/<run_id>/final/ (opcional)",
                    },
                },
                "required": ["reason"],
            },
        }

    def run(self, reason: str = "", target: str = "final", **kwargs) -> str:
        src = PATHS["current"]
        if not (src / "index.html").exists():
            return f"ERROR: no hay candidato en {src}"
        dst = PATHS["runs"] / kwargs.get("run_id", "latest") / target
        dst.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        return f"OK: candidato exportado a {dst}\nRazón: {reason or '(no dada)'}"