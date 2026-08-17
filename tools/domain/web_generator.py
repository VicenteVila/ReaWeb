"""Generación de código web. Usa un SUBAGENTE (LLM separado) para producir los
archivos, manteniendo limpio el contexto del agente principal (patrón ReASearch)."""
from __future__ import annotations

import shutil
from pathlib import Path

from config import PATHS
from tools.base import Tool


def _is_safe_filename(name: str) -> bool:
    """Nombre de archivo permitido: plano (sin rutas ni subdirectorios)."""
    return (
        bool(name)
        and not name.startswith(".")
        and "/" not in name
        and "\\" not in name
        and " " not in name
        and not name.startswith(("<", "{", "const", "function", "/*"))
    )


def _infer_file(content: str) -> str | None:
    """Infere el nombre del archivo por el contenido cuando el subagente omitió
    la línea del nombre (pega el HTML directamente tras ===FILE===)."""
    head = content.strip()[:200].lower()
    if head.startswith("<!doctype") or "<html" in head or head.startswith("{"):
        return "index.html"
    if head.startswith(":root") or "{" in head and "}" in head and ("color" in head or "font" in head or ";" in head):
        return "styles.css"
    if "const " in head or "let " in head or "function " in head or "document." in head:
        return "app.js"
    return None


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

SECCIONES OBLIGATORIAS DE LA TAREA (inclúyelas TODAS en el HTML, con id o class
descriptivos; el evaluador verifica su presencia):
{sections}

REFERENCIA (HTML analizado de una URL; adapta su estructura, estética y patrones
de contenido a la tarea, NO copies su contenido literal):
{reference}

DATOS DEL GRAFO DE CONOCIMIENTOS (si existe, úsalos literalmente para el grafo SVG:
nodo raíz con nombre y email, un nodo por repo, y las categorías sujet arXiv por repo):
{graph_data}

CÓDIGO ACTUAL EN workspace/current (es el punto de partida a MUTAR, no lo ignores).
Mantén TODO lo que funcione y evoluciona el diseño: estructura, interacciones,
enlaces, animaciones y estética. NO regeneres desde cero a menos que sea la
primera versión. Si este bloque está vacío, esta es la versión inicial (H0):
{current_code}

INSTRUCCIÓN DE MUTACIÓN (obligatoria):
- Compara tu salida con {current_code} y conserva TODA la funcionalidad existente
  (enlaces, hover, subnodos, temas, animaciones). Solo cambia lo que el objetivo
  de mejora pide. Si el objetivo es estético, mantén la estructura e interacciones
  intactas y mejora solo lo visual (spacing, alineación, centrado, color, tipografía).
- No simplifiques ni elimines archivos ni bloques. Tu salida debe tener, como mínimo,
  la misma riqueza de código que {current_code}.

REQUISITOS:
1. Una página HTML autocontenida (index.html) con CSS en styles.css y JS en app.js.
2. Diseño responsive (mobile-first), semántico, accesible.
3. Incluye: <!DOCTYPE html>, lang, charset, viewport, title (<60 chars), meta description,
   OG tags, un solo <h1>, alt en imágenes, atributos aria donde haga falta.
4. Las imágenes pueden ser inline SVG o URLs de ejemplo. No uses rutas que no existan.
5. Máximo 1 <style> y 1 <script>; usa defer.
6. Sin console.log. Sin dependencias externas pesadas (no uses CDN de Tailwind/Bootstrap).
7. Sin archivos extra en subdirectorios: todo en la raíz (index.html, styles.css, app.js).

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


class FetchUrl(Tool):
    name = "fetch_url"
    description = (
        "Descarga el HTML crudo de una URL y lo guarda como referencia de diseño "
        "(runs/<run_id>/reference/ y workspace/reference.html). Devuelve un extracto "
        "analizado (title, meta, headings, nav, estructura) para adaptar su contenido "
        "a la tarea. Úsala al inicio para inspirar H0."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL http(s) a analizar"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Longitud máxima del extracto devuelto (default 8000)",
                    },
                },
                "required": ["url"],
            },
        }

    def run(self, url: str = "", max_chars: int = 8000, **kwargs) -> str:
        import gzip
        import re
        import urllib.request
        from urllib.parse import urlparse

        if not re.match(r"^https?://", url):
            return f"ERROR: URL inválida: {url!r} (debe empezar por http:// o https://)"

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return f"ERROR: URL inválida: {url!r}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                html = raw.decode("utf-8", errors="replace")
        except Exception as e:
            return f"ERROR descargando {url}: {e}"

        # guardar referencia: fuente en runs/<run_id>/reference/ + copia para el generador
        run_id = kwargs.get("run_id")
        ref_dir = PATHS["runs"] / run_id / "reference"
        ref_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]", "_", parsed.netloc + parsed.path)
        ref_path = ref_dir / f"{safe[:80]}.html"
        ref_path.write_text(html)
        (PATHS["current"].parent / "reference.html").write_text(html)  # workspace/reference.html

        excerpt = self._excerpt(html, max_chars=max_chars)
        return (
            f"OK: HTML descargado ({len(html)} chars, {resp.status}). "
            f"Guardado en {ref_path} y workspace/reference.html.\n\n"
            f"=== EXTRACTO ANALIZADO ===\n{excerpt}"
        )

    @staticmethod
    def _excerpt(html: str, max_chars: int = 8000) -> str:
        import re

        # quitar scripts y comentarios para que quepa más estructura
        cleaned = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        cleaned = re.sub(r"<!--[\s\S]*?-->", "", cleaned)
        cleaned = re.sub(r"<style[\s\S]*?</style>", "", cleaned, flags=re.I)

        def strip(tag: str) -> str:
            return re.sub(r"<[^>]+>", " ", tag)

        parts = []
        t = re.search(r"<title[^>]*>(.*?)</title>", cleaned, re.S | re.I)
        if t:
            parts.append(f"TITLE: {strip(t.group(1)).strip()[:120]}")
        for m in re.finditer(r'<meta\s+name=["\'](description|keywords)["\']\s+content=["\']([^"\']*)', cleaned, re.I):
            parts.append(f"META {m.group(1)}: {m.group(2)[:200]}")
        for m in re.finditer(r"<h([1-3])[^>]*>([\s\S]*?)</h\1>", cleaned, re.I):
            txt = strip(m.group(2)).strip()
            if txt:
                parts.append(f"H{m.group(1)}: {txt[:120]}")
        nav = re.search(r"<nav[^>]*>([\s\S]*?)</nav>", cleaned, re.I | re.S)
        if nav:
            links = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)</a>', nav.group(1), re.I | re.S)
            nav_links = [f"{strip(t).strip()[:30]} -> {h[:50]}" for h, t in links[:10]]
            if nav_links:
                parts.append("NAV:")
                parts.extend(f"  - {l}" for l in nav_links)
        m = re.search(r'<main[\s\S]*?>([\s\S]*?)</main>', cleaned, re.I | re.S)
        if m:
            body = m.group(1)
        else:
            body = cleaned
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            parts.append(f"CONTENIDO: {text[:1200]}")
        classes = re.findall(r'class="([^"]{4,})"', cleaned)
        if classes:
            uniq = sorted(set(classes))[:15]
            parts.append(f"CLASSES (muestra): {', '.join(uniq)[:400]}")
        out = "\n".join(parts)
        return out[:max_chars] if len(out) > max_chars else out


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
        self.task_text = task
        self.rules = rules
        self.stack = stack
        self.improve = improve
        from .evaluator import extract_requirements, extract_sections
        self.requirements = requirements if requirements is not None else extract_requirements(task)
        self.sections = extract_sections(task)
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

    @staticmethod
    def _parse_files(text: str) -> tuple[dict, bool]:
        """Extrae {nombre: contenido} del output del subagente.

        Acepta dos formatos:
          - Delimitado por ===FILE=== (línea siguiente = nombre del archivo).
          - Bloques ```nombre``` (o ```html```/```css```/```js```) de markdown.
        Devuelve (files, fallback_used). fallback_used=True si hubo que recurrir
        al heurístico de inferencia por contenido.
        """
        files: dict[str, str] = {}
        fallback = False

        blocks = text.split("===FILE===")
        if len(blocks) > 1:
            for block in blocks[1:]:
                body = block.strip("\n")
                if not body:
                    continue
                lines = body.split("\n", 1)
                fname = lines[0].strip()
                content = lines[1] if len(lines) == 2 else ""
                if _is_safe_filename(fname):
                    files[fname] = content
                else:
                    # El subagente omitió la línea del nombre (HTML pegado tras ===FILE===):
                    # inferir el archivo por contenido.
                    inferred = _infer_file(body)
                    if inferred:
                        files.setdefault(inferred, body)
                        fallback = True
        elif not files:
            files, f2 = GenerateCandidate._parse_files_fallback(text)
            fallback = fallback or f2

        return files, fallback

    @staticmethod
    def _parse_files_fallback(text: str) -> tuple[dict, bool]:
        """Heurístico de último recurso: infiere archivos por contenido si no hay
        delimitadores claros (p. ej. el modelo devolvió todo pegado o con ```)."""
        import re

        files: dict[str, str] = {}

        # 1) bloques de código con nombre explícito (```html / index.html ...```)
        for m in re.finditer(r"```(?:html|css|js)?\s*([\w.]+)?\s*\n(.*?)```", text, re.S):
            name, content = m.group(1), m.group(2)
            if name and _is_safe_filename(name):
                files.setdefault(name, content)
                continue
            inferred = _infer_file(content)
            if inferred:
                files.setdefault(inferred, content)

        # 2) si aún falta algo, escanear el texto crudo por segmentos plausibles
        for fname, pattern in (
            ("index.html", r"<!DOCTYPE\s+html|<\s*html\b"),
            ("styles.css", r"\.body\s*\{|^\s*\*\{\s*$"),
            ("app.js", r"\bconst\s+\w+\s*=\s*document\.|\baddEventListener\s*\("),
        ):
            if fname in files:
                continue
            if re.search(pattern, text, re.I | re.S):
                files[fname] = text
        return files, True

    @staticmethod
    def _build_current_code() -> str:
        """Seriealiza el candidato actual en workspace/current para que el subagente
        lo mute en lugar de regenerar desde cero (capa evolutiva estética: las
        mejoras visuales se acumulan entre hipótesis)."""
        target = PATHS["current"]
        parts = []
        for fname in ("index.html", "styles.css", "app.js"):
            f = target / fname
            if f.exists():
                content = f.read_text(errors="replace")
                parts.append(f"--- {fname} ({len(content)} chars) ---\n{content[:6000]}")
        if not parts:
            return "(workspace vacío: versión inicial desde cero)"
        return "\n\n".join(parts)[:20000]

    def run(self, objective: str = "", **kwargs) -> str:
        from .evaluator import evaluate

        ref_path = PATHS["current"].parent / "reference.html"
        if ref_path.exists():
            ref_text = ref_path.read_text(errors="replace")
            # recortar a lo útil para no inflar el prompt del subagente
            reference = f"HTML de referencia ({len(ref_text)} chars):\n" + ref_text[:8000]
        else:
            reference = "(sin referencia: genera desde cero)"

        graph_path = PATHS["current"] / "graph_data.json"
        if graph_path.exists():
            graph_text = graph_path.read_text(errors="replace")
            graph_data = f"(graph_data.json, {len(graph_text)} chars):\n" + graph_text[:6000]
        else:
            graph_data = "(sin graph_data.json: no hay grafo de datos; si la tarea pide un grafo, llama antes a fetch_repo_topics)"

        current_code = self._build_current_code()

        prompt = GENERATOR_PROMPT.format(
            task=self.task,
            archetype=self.archetype,
            rules=self.rules[:4000],
            stack=self.stack[:2000],
            improve=objective or self.improve or "Sin mejora específica (versión inicial)",
            requirements="\n".join(f"- {r}" for r in self.requirements) if self.requirements else "(ninguno específico)",
            sections="\n".join(f"- {s}" for s in self.sections) if self.sections else "(no exigidas)",
            reference=reference,
            graph_data=graph_data,
            current_code=current_code,
        )
        out = self.llm.generate(prompt, temperature=0.7)
        text = out.text

        files, vuln_files = self._parse_files(text)
        if not files:
            files, vuln_files = self._parse_files_fallback(text)
            vuln_files = vuln_files or True

        if not files or "index.html" not in files:
            return f"ERROR: no se pudo extraer archivos del output del subagente.\n---\n{text[:1500]}"

        target = PATHS["current"]
        target.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            # solo permitir nombres seguros
            if fname.startswith(".") or "/" in fname or "\\" in fname:
                continue
            (target / fname).write_text(content)

        metrics = evaluate(target, requirements=self.requirements, structure=self.sections)
        self.last_functional_tests = metrics.get("functional_tests")
        task_metrics = f" task={metrics.get('task')}" if metrics.get('task') is not None else ""
        struct_metrics = f" structure={metrics.get('structure')}" if metrics.get('structure') is not None else ""
        func_metrics = f" functional={metrics.get('functional')}" if metrics.get('functional') is not None else ""
        summary = (
            f"Métricas: total={metrics.get('total')} seo={metrics.get('seo')} "
            f"a11y={metrics.get('a11y')} perf={metrics.get('performance')} "
            f"resp={metrics.get('responsive')} bp={metrics.get('best_practices')} "
            f"visual={metrics.get('visual')}{task_metrics}{struct_metrics}{func_metrics}"
        )
        # CHECKLIST DE SUBTAREAS (loop F1): qué subtarea falla y por qué
        try:
            from .evaluator import format_subtasks_status
            _h = (target / "index.html").read_text(errors="replace") if (target / "index.html").exists() else ""
            _css = " ".join(p.read_text(errors="replace") for p in target.glob("*.css"))
            _js = " ".join(p.read_text(errors="replace") for p in target.glob("*.js"))
            _fts = metrics.get("functional_tests")
            summary += "\n" + format_subtasks_status(_h, _css, _js, self.task_text or "", _fts)
        except Exception:
            pass
        gate_lines = []
        for cat, lst in (metrics.get("gates") or {}).items():
            if lst:
                gate_lines.append(f"{cat}: {', '.join(lst)}")
        if gate_lines:
            summary += "\nGATE BLOQUEANTE (total capado): faltan secciones obligatorias — " + "; ".join(gate_lines)
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

    def __init__(self, requirements: list[str] | None = None, task: str = ""):
        from .evaluator import extract_requirements, extract_sections
        self.requirements = requirements or extract_requirements(task) if task else []
        self.sections = extract_sections(task) if task else []
        self.task_text = task
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
        m1 = evaluate(target, requirements=self.requirements, structure=self.sections)
        result = m1.copy()
        self.last_functional_tests = m1.get("functional_tests")
        if verify:
            m2 = evaluate(target, requirements=self.requirements, structure=self.sections)
            for k in ("total", "seo", "a11y", "performance", "responsive", "best_practices", "visual", "task", "structure", "functional"):
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
        struct_part = f" structure={result.get('structure')}" if result.get('structure') is not None else ""
        func_part = f" functional={result.get('functional')}" if result.get('functional') is not None else ""
        gate_lines = []
        for cat, lst in (result.get("gates") or {}).items():
            if lst:
                gate_lines.append(f"{cat}: {', '.join(lst)}")
        res = (
            f"total={result.get('total')} | seo={result.get('seo')} a11y={result.get('a11y')} "
            f"perf={result.get('performance')} resp={result.get('responsive')} "
            f"bp={result.get('best_practices')} visual={result.get('visual')}{task_part}{struct_part}{func_part} | verificación={result.get('verification')}"
        )
        if gate_lines:
            res += "\nGATE BLOQUEANTE (total capado): faltan secciones obligatorias — " + "; ".join(gate_lines)
        if fail_lines:
            res += "\nFallos detectados:\n" + "\n".join(fail_lines)
        res += f"\nArchivos: {result.get('files')}"
        # CHECKLIST DE SUBTAREAS (loop F1): qué subtarea falla y por qué
        try:
            from .evaluator import format_subtasks_status
            _h = (target / "index.html").read_text(errors="replace") if (target / "index.html").exists() else ""
            _css = " ".join(p.read_text(errors="replace") for p in target.glob("*.css"))
            _js = " ".join(p.read_text(errors="replace") for p in target.glob("*.js"))
            _fts = result.get("functional_tests")
            res += "\n" + format_subtasks_status(_h, _css, _js, self.task_text or "", _fts)
        except Exception:
            pass
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


class RevertWorkspace(Tool):
    name = "revert_workspace"
    description = (
        "Restaura workspace/current desde un snapshot congelado de la run "
        "(runs/<run_id>/candidates/<node_id>/). Úsala cuando una mutación haya "
        "EMPEORADO el candidato o haya dejado el workspace inestable: en vez de "
        "reconstruir manualmente, vuelve a un candidato previo (el mejor conocido "
        "por defecto) y sigue iterando desde ahí. Los snapshots se congelan tras "
        "cada generate_candidate (H0, H1, H2...)."
    )

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "candidate": {
                        "type": "string",
                        "description": "Id del candidato a restaurar (p. ej. 'H2'). "
                                       "Vacío = restaurar el MEJOR candidato de la run.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Por qué se revierte (para el transcript)",
                    },
                },
            },
        }

    def run(self, candidate: str = "", reason: str = "", **kwargs) -> str:
        import shutil
        run_id = kwargs.get("run_id") or ""
        candidates_dir = PATHS["runs"] / (run_id or "latest") / "candidates"
        src = None
        if candidate:
            src = candidates_dir / candidate
            if not (src / "index.html").exists():
                return f"ERROR: no existe snapshot {candidate} en {candidates_dir}"
        else:
            # elegir el mejor snapshot por antigüedad de archivos no es robusto;
            # el agente pasa run_id y candidate explícito normalmente. Sin
            # candidate, buscar el índice numerado más alto (H<n>).
            best = None
            for d in sorted(candidates_dir.glob("H*")):
                if (d / "index.html").exists():
                    best = d
            src = best
            if src is None:
                return f"ERROR: no hay snapshots en {candidates_dir}"
            candidate = src.name
        dst = PATHS["current"]
        if dst.exists():
            for f in dst.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dst / f.name)
            elif f.is_dir():
                shutil.copytree(f, dst / f.name)
        return f"OK: workspace/current restaurado desde {candidate}\nRazón: {reason or '(no dada)'}"