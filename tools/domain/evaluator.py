"""Evaluador ligero de sitios web estáticos. Analiza archivos HTML/CSS/JS sin
necesidad de navegador y produce métricas estilo Lighthouse (0-100 por categoría).

Categorías: seo, a11y, performance, responsive, best_practices, visual, task
"""
from __future__ import annotations

import re
from pathlib import Path

SEO_CHECKS = {
    "title": ("<title> presente", lambda h: "<title" in h and "</title>" in h),
    "title_len": (
        "title < 60 chars",
        lambda h: len(re.sub(r"<[^>]+>", "", re.search(r"<title.*?>(.*?)</title>", h, re.S).group(1)) if re.search(r"<title.*?>(.*?)</title>", h, re.S) else "") < 60,
    ),
    "meta_desc": (
        "meta description con contenido",
        lambda h: bool(re.search(r'<meta\s+name=["\']description["\'][^>]*content=["\'][^"\']+["\']', h, re.I)
                      or re.search(r'<meta\s+content=["\'][^"\']+["\'][^>]*name=["\']description["\']', h, re.I)),
    ),
    "og": ("Open Graph tags con contenido", lambda h: bool(re.search(r'property=["\']og:(title|description|image)["\'][^>]*content=["\'][^"\']+["\']', h, re.I))),
    "h1": ("Un solo <h1>", lambda h: len(re.findall(r"<h1[ >]", h)) == 1),
    "lang": ("Atributo lang en <html>", lambda h: re.search(r'<html[^>]*\blang=', h) is not None),
    "viewport": ("viewport meta", lambda h: 'name="viewport"' in h or "name='viewport'" in h),
    "canonical": ("canonical con href", lambda h: bool(re.search(r'rel=["\']canonical["\'][^>]*href=["\'][^"\']+["\']', h, re.I)
                      or re.search(r'href=["\'][^"\']+["\'][^>]*rel=["\']canonical["\']', h, re.I))),
}

A11Y_CHECKS = {
    "alt_images": (
        "imágenes con alt",
        lambda h: all(re.search(r'alt=["\']', tag_attrs) is not None for tag_attrs in re.findall(r"<img\b([^>]*)>", h))
        if re.findall(r"<img\b([^>]*)>", h) else True,
    ),
    "labels_inputs": (
        "inputs con label[for] o aria-label",
        lambda h: _inputs_labeled(h),
    ),
    "skip_link": ("skip link", lambda h: re.search(r'class=["\'][^"\']*skip', h) is not None or "skip-link" in h),
    "lang_set": ("lang set (a11y)", lambda h: re.search(r'<html[^>]*\blang=', h) is not None),
    "semantic": ("usa main/section/nav", lambda h: re.search(r"<(main|section|nav|article)\b", h) is not None),
}

PERF_CHECKS = {
    "html_size": ("HTML < 100KB", lambda h: len(h) < 100_000),
    "no_inline_css": ("CSS en archivo, no inline masivo", lambda h: len(re.findall(r"<style[ >]", h)) <= 2),
    "no_inline_js": ("JS en archivo, no inline masivo", lambda h: len(re.findall(r"<script[^>]*>", h)) <= 3),
    "modern_img": ("imágenes en webp/avif", lambda h: _has_modern_images(h)),
    "defer_js": ("scripts con defer/type=module", lambda h: _scripts_async(h)),
}

RESP_CHECKS = {
    "viewport_mobile": ("viewport para mobile", lambda h: 'name="viewport"' in h),
    "media_queries": ("media queries en CSS", lambda css: "@media" in css),
    "flexgrid": ("usa flex o grid", lambda css: re.search(r"display\s*:\s*(flex|grid|inline-flex)", css) is not None),
    "img_responsive": ("imágenes con width/height o max-width", lambda h: _img_responsive(h)),
}

BP_CHECKS = {
    "doctype": ("doctype presente", lambda h: h.lstrip().lower().startswith("<!doctype html>")),
    "no_console": ("sin console.log (fuera de comentarios)", lambda js: "console.log" not in _strip_js_comments(js)),
    "charset": ("meta charset", lambda h: re.search(r'<meta[^>]+charset=["\']?utf-?8', h, re.I) is not None),
    "favicon": ("favicon con href", lambda h: bool(re.search(r'rel=["\'][^"\']*icon["\'][^>]*href=["\'][^"\']+["\']', h, re.I))),
}


def _strip_js_comments(js: str) -> str:
    """Elimina comentarios // y /* */ (aproximación sin tóxicos) para que
    un console.log dentro de un comentario no cuente como fallo."""
    s = re.sub(r"//[^\n]*", "", js)
    s = re.sub(r"/\*[\s\S]*?\*/", "", s)
    return s

VISUAL_CHECKS = {
    "css_animations": (
        "animaciones CSS reales (@keyframes usado por animation)",
        lambda c: _has_real_css_animations(c),
    ),
    "css_transitions": (
        "transiciones CSS reales (transition en :hover/:focus/:active)",
        lambda c: _has_real_transitions(c),
    ),
    "gradients": (
        "gradientes usados en propiedades",
        lambda c: _has_real_gradients(c),
    ),
    "canvas_animated": (
        "canvas animado real (requestAnimationFrame + dibujo)",
        lambda c: _has_animated_canvas(c),
    ),
    "no_dead_canvas": (
        "canvas declarado no debe quedarse sin animar",
        lambda c: _no_dead_canvas(c),
    ),
    "dark_mode": (
        "dark mode real (prefers-color-scheme en CSS o matchMedia)",
        lambda c: _has_dark_mode(c),
    ),
    "theme_persist": (
        "tema persistido en localStorage",
        lambda c: "localStorage" in c and ("theme" in c.lower() or "dark" in c.lower() or "color-scheme" in c),
    ),
    "scroll_reveal": (
        "scroll-reveal real (IntersectionObserver o listener scroll)",
        lambda c: _has_scroll_reveal(c),
    ),
    "reduced_motion": (
        "respeto a prefers-reduced-motion",
        lambda c: "prefers-reduced-motion" in c,
    ),
    "hover_effects": (
        "hover effects reales (:hover + transition/transform)",
        lambda c: _has_hover_effects(c),
    ),
    "sticky_nav": (
        "nav sticky/fixed",
        lambda c: "position:sticky" in c or "position: sticky" in c or "position:fixed" in c or "position: fixed" in c,
    ),
    "microinteractions": (
        "microinteracciones reales (:active/:focus o mousemove/tilt)",
        lambda c: _has_microinteractions(c),
    ),
}


def _has_real_css_animations(c: str) -> bool:
    """@keyframes <nombre> definido Y referenciado por animation/animation-name."""
    names = re.findall(r"@keyframes\s+([A-Za-z0-9_-]+)", c)
    for name in names:
        if re.search(r"(?:animation|animation-name)\s*:[^;{}]*\b" + re.escape(name) + r"\b", c):
            return True
    return False


def _has_real_transitions(c: str) -> bool:
    """transition presente junto a un disparador real (:hover/:focus/:active)."""
    if "transition" not in c:
        return False
    return bool(re.search(r":[a-z-]*:?(hover|focus|active)\b", c))


def _has_real_gradients(c: str) -> bool:
    """Gradiente usado como valor de propiedad (no solo mencionado, ni en comentario)."""
    c = re.sub(r"/\*[\s\S]*?\*/", "", c)
    return bool(
        re.search(
            r"(?:background|background-image|border-image|filter|mask|outline|box-shadow)\s*:[^;}]*?"
            r"(?:linear|radial|conic)-gradient",
            c,
        )
    )


def _has_animated_canvas(c: str) -> bool:
    """Canvas que de verdad anima: requestAnimationFrame + getContext + dibujo."""
    if "requestAnimationFrame" not in c or "getContext" not in c:
        return False
    return bool(re.search(r"(?:fillRect|strokeRect|clearRect|arc\(|fill\(|stroke\(|drawImage|fillText|bezierCurveTo|lineTo)", c))


def _no_dead_canvas(c: str) -> bool:
    """Si hay canvas/getContext, exige que además haya animación real; si no hay
    canvas en absoluto, no penaliza."""
    if "<canvas" not in c and "getContext" not in c:
        return True
    return _has_animated_canvas(c)


def _has_dark_mode(c: str) -> bool:
    """prefers-color-scheme como media query CSS o matchMedia JS."""
    if re.search(r"@media\s*[({][^}]*prefers-color-scheme", c):
        return True
    return bool(re.search(r"matchMedia\s*\(\s*['\"]\(prefers-color-scheme", c))


def _has_scroll_reveal(c: str) -> bool:
    """IntersectionObserver o listener de scroll real."""
    if "IntersectionObserver" in c:
        return True
    return bool(re.search(r"addEventListener\s*\(\s*['\"]scroll['\"]", c)) or "onscroll" in c


def _has_hover_effects(c: str) -> bool:
    """:hover real con transition o transform en la misma regla."""
    if ":hover" not in c:
        return False
    return bool(re.search(r"[^{}]*:hover\s*\{[^}]*?(transition|transform)[^}]*\}", c))


def _has_microinteractions(c: str) -> bool:
    """:active/:focus con transición, o listener de mousemove/tilt real."""
    if re.search(r":(active|focus)\b", c) and "transition" in c:
        return True
    if re.search(r"addEventListener\s*\(\s*['\"](mousemove|pointermove|touchmove)['\"]", c):
        return True
    return bool(re.search(r"transform\s*:\s*perspective\(|rotateX\(|rotateY\(", c) and ":hover" in c)


def extract_requirements(task: str, max_items: int = 10) -> list[str]:
    """Extrae requisitos verificables de la tarea estipulada:
    - URLs de repositorios (github.com/usuario/repo, gitlab.com/..., etc.)
    - menciones 'github.com/usuario' (para exigir al menos enlaces a ese perfil)
    - nombres de repos en PascalCase cuando la tarea menciona una cuenta github/gitlab
    """
    reqs: list[str] = []
    # 1) URLs de repos completas (se ignoran templates/placeholders con < o ${)
    for m in re.finditer(r"https?://[^\s)\"']+", task):
        url = m.group(0).rstrip(",.;")
        if "<" in url or "${" in url or "{" in url:
            continue
        if any(h in url for h in ("github.com", "gitlab.com", "bitbucket.org", "hub.docker.com")):
            if url not in reqs:
                reqs.append(url)

    # 2) cuentas owner mencionadas (github.com/usuario / gitlab.com/usuario)
    owners = set()
    for m in re.finditer(r"(?:github|gitlab)\.com/([A-Za-z0-9_.-]+)", task):
        owners.add(m.group(1))
    for owner in sorted(owners):
        base = f"github.com/{owner}"
        if not any(f"{base}/" in r for r in reqs) and base not in reqs:
            reqs.append(base)

    # 3) nombres de repos en PascalCase (se exige que aparezcan en el código)
    if owners:
        seen = set()
        skip = {"HTML", "CSS", "JS", "GitHub", "Python", "JavaScript", "TypeScript",
                "Landing", "Portfolio", "LandingPage", "Vicente", "Vila", "Repo", "Repos",
                "Cada", "Para", "Con", "Sin", "Una", "Un", "Los", "Las", "Son", "Web",
                "Enfoque", "Diseño", "Diseños", "Estética", "Visual", "Visuales",
                "Interactivos", "Interactivo", "Interactivas", "Interactiva", "Moderno",
                "Modernos", "Actuales", "Actual", "Tarea", "Proyecto", "Proyectos",
                "Página", "Pagina", "Páginas", "Paginas", "Contenido", "Sección", "Seccion",
                "Secciones", "Cada", "Tiene", "Debe", "Deben", "Más", "Mas", "Todo", "Todos",
                "Primer", "Segundo", "Tercer", "Uso", "Usa", "Usar", "Lista", "Listado",
                "Nombre", "Nombres", "Descripción", "Descripcion", "Lenguaje", "Etiqueta",
                "Etiquetas", "Categoría", "Categoria", "Categorías", "Categorias", "Perfil",
                "Cuenta", "Usuario", "Usuarios", "Repositorio", "Repositorios", "Biblioteca",
                "Bibliotecas", "Librería", "Librerias", "Agente", "Agentes", "AgentesIA",
                "IA", "GenAI", "AI", "OpenAI", "Gemini", "Groq", "Ollama", "Langfuse"}
        for m in re.finditer(r"([A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)", task):
            name = m.group(1)
            if name in seen or name in skip or len(name) < 4:
                continue
            seen.add(name)
            if name not in reqs:
                reqs.append(name)
            if len(reqs) >= max_items:
                break
    return list(dict.fromkeys(reqs[:max_items]))


def _inputs_labeled(h: str) -> bool:
    inputs = re.findall(r"<input\b([^>]*)>", h)
    if not inputs:
        return True
    for attrs in inputs:
        if re.search(r'aria-label=["\']', attrs):
            continue
        # input tipo hidden no necesita label
        if 'type="hidden"' in attrs:
            continue
        # exige label[for=id] con el mismo id, no basta con tener id
        m = re.search(r'\bid=["\']([^"\']+)["\']', attrs)
        if not m:
            return False
        fid = m.group(1)
        if not re.search(r'<label\b[^>]*\bfor=["\']' + re.escape(fid) + r'["\']', h):
            return False
    return True


def _has_modern_images(h: str) -> bool:
    imgs = re.findall(r'src=["\']([^"\']+)["\']', h)
    if not imgs:
        # Sin imágenes -> se considera OK
        return True
    return any(ext in i.lower() for i in imgs for ext in (".webp", ".avif"))


def _scripts_async(h: str) -> bool:
    scripts = re.findall(r"<script\b([^>]*)>", h)
    if not scripts:
        return True
    return any("defer" in s or "type=\"module\"" in s for s in scripts)


def _img_responsive(h: str) -> bool:
    imgs = re.findall(r"<img\b([^>]*)>", h)
    if not imgs:
        return True
    ok = 0
    for attrs in imgs:
        if "width=" in attrs or "max-width" in attrs or "height=" in attrs or 'srcset' in attrs:
            ok += 1
    return ok == len(imgs)


def _score(checks: list[tuple[str, str, object]], context: str) -> tuple[int, list[str]]:
    passed = [name for _, name, fn in checks if bool(fn(context))]
    fails = [key for key, name, fn in checks if not bool(fn(context))]
    pct = int(100 * len(passed) / len(checks)) if checks else 100
    return pct, fails


WEIGHTS = {
    "seo": 1.0,
    "a11y": 1.0,
    "performance": 1.0,
    "responsive": 1.0,
    "best_practices": 1.0,
    "visual": 2.0,
    "task": 1.0,
}


def evaluate(project_dir: str | Path, requirements: list[str] | None = None, weights: dict | None = None) -> dict:
    """Evalúa un proyecto web estático. Devuelve métricas por categoría y total.

    requirements: lista de subcadenas que DEBEN aparecer en el código (html+css+js)
    concatenado. Si se pasan, se añade la categoría 'task' al total (requisitos de
    la tarea estipulada presentes). Si no, 'task' se ignora.

    'visual' es un proxy de diseño moderno/interactivo que exige efectos REALES
    (canvas con requestAnimationFrame+dibujo, @keyframes usado, gradientes en
    propiedades, transition con disparador, etc.), no solo menciones.

    total = media PONDERADA de las categorías (WEIGHTS; visual pesa 2.0 por
    defecto). Se puede sobrescribir con weights=.
    """
    project_dir = Path(project_dir)
    html_files = sorted(project_dir.rglob("*.html"))
    css_text = " ".join(p.read_text(errors="replace") for p in project_dir.rglob("*.css"))
    js_text = " ".join(p.read_text(errors="replace") for p in project_dir.rglob("*.js"))

    if not html_files:
        return {
            "error": "No hay archivos HTML",
            "total": 0,
            "files": 0,
        }

    h = html_files[0].read_text(errors="replace")
    n_html = len(html_files)

    combined_assets = h + "\n" + css_text + "\n" + js_text

    seo, seo_fails = _score([(k,) + v for k, v in SEO_CHECKS.items()], h)
    a11y, a11y_fails = _score([(k,) + v for k, v in A11Y_CHECKS.items()], h)
    perf, perf_fails = _score([(k,) + v for k, v in PERF_CHECKS.items()], h)
    # responsive y best_practices mezclan checks de html+css+js -> evaluar contra
    # el contenido combinado (no solo HTML).
    resp, resp_fails = _score([(k,) + v for k, v in RESP_CHECKS.items()], combined_assets)
    bp, bp_fails = _score([(k,) + v for k, v in BP_CHECKS.items()], combined_assets)

    # Categoría 'visual': señales estáticas de diseño moderno/interactivo.
    visual, visual_fails = _score([(k,) + v for k, v in VISUAL_CHECKS.items()], combined_assets)

    # Categoría 'task': requisitos de la tarea presentes en el código
    requirements = requirements or []
    task_fails = [r for r in requirements if r not in combined_assets]
    task = int(100 * (len(requirements) - len(task_fails)) / len(requirements)) if requirements else None

    html_bytes = sum(p.stat().st_size for p in html_files)
    css_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.css"))
    js_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.js"))
    img_bytes = sum(p.stat().st_size for p in project_dir.rglob("*")
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"))

    axes = {"seo": seo, "a11y": a11y, "performance": perf, "responsive": resp, "best_practices": bp, "visual": visual}
    if task is not None:
        axes["task"] = task
    w = {**WEIGHTS, **(weights or {})}
    num = sum(axes[k] * w.get(k, 1.0) for k in axes)
    den = sum(w.get(k, 1.0) for k in axes)
    total = int(num / den) if den else 0

    return {
        "total": total,
        "seo": seo,
        "a11y": a11y,
        "performance": perf,
        "responsive": resp,
        "best_practices": bp,
        "visual": visual,
        "task": task,
        "failures": {
            "seo": seo_fails,
            "a11y": a11y_fails,
            "performance": perf_fails,
            "responsive": resp_fails,
            "best_practices": bp_fails,
            "visual": visual_fails,
            "task": task_fails,
        },
        "files": {
            "html": n_html,
            "total_html_kb": round(html_bytes / 1024, 1),
            "total_css_kb": round(css_bytes / 1024, 1),
            "total_js_kb": round(js_bytes / 1024, 1),
            "total_img_kb": round(img_bytes / 1024, 1),
        },
    }