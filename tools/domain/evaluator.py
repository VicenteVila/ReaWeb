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
    "flexgrid": (
        "usa flex o grid (CSS literal o clases tipo Tailwind)",
        lambda css: (re.search(r"display\s*:\s*(flex|grid|inline-flex)", css) is not None)
                    or bool(re.search(r'class=["\'][^"\']*\b(?:grid|flex|md:grid-cols-\d|grid-cols-\d)\b', css)),
    ),
    "img_responsive": ("imágenes con width/height o max-width", lambda h: _img_responsive(h)),
}

BP_CHECKS = {
    "doctype": ("doctype presente", lambda h: h.lstrip().lower().startswith("<!doctype html>")),
    "no_console": ("sin console.log (fuera de comentarios)", lambda js: "console.log" not in _strip_js_comments(js)),
    "charset": ("meta charset", lambda h: re.search(r'<meta[^>]+charset=["\']?utf-?8', h, re.I) is not None),
    "favicon": ("favicon con href", lambda h: bool(re.search(r'rel=["\'][^"\']*icon["\'][^>]*href=["\'][^"\']+["\']', h, re.I))),
    "no_cdn": (
        "sin librerías/frameworks externos vía CDN (Tailwind, Bootstrap...)",
        lambda c: not re.search(r'<(?:script|link)\s[^>]*(?:src|href)=["\']https?://[^"\']*(?:cdn|unpkg|jsdelivr|tailwindcss|bootstrap|googleapis)[^"\']*', c, re.I),
    ),
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
    "content_richness": (
        "contenido real: >=3 secciones semánticas o >=80 palabras en el body",
        lambda c: _has_content_richness(c),
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
    """Canvas que de verdad anima con DINÁMICA: requestAnimationFrame + getContext +
    dibujo que varía (coordenadas/valores dependientes de una variable, Math.random,
    Date.now/performance.now, contador incremental o parámetro t del callback).

    Un fillRect estático en bucle (mismas coordenadas siempre) NO cuenta como
    animación real: es un canvas 'encendido' pero visualmente congelado.
    """
    if "requestAnimationFrame" not in c or "getContext" not in c:
        return False
    if not re.search(r"(?:fillRect|strokeRect|clearRect|arc\(|fill\(|stroke\(|drawImage|fillText|bezierCurveTo|lineTo)", c):
        return False
    # exige señal de dinamismo: variable/tiempo/aleatorio/contador/parámetro t
    dynamic = (
        re.search(r"Math\.random", c)
        or re.search(r"Date\.now|performance\.now", c)
        or re.search(r"requestAnimationFrame\s*\(\s*\(?\s*t\s*\)?\s*=>", c)
        or re.search(r"(?:let|const|var)\s+\w+\s*=\s*0\s*;\s*[\s\S]*\+\+|--", c)
        or re.search(r"(?:let|const|var)\s+\w+\s*(?:=\s*Math\.|;\s*[\s\S]{0,200}?ctx\.)", c)
    )
    return bool(dynamic)


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


def _has_content_richness(c: str) -> bool:
    """Exige que la página tenga contenido real: >=3 secciones semánticas o
    >=80 palabras de texto visible. Evita que una landing vacía ('tokens') gane."""
    sections = len(re.findall(r"<(section|article|nav|header|footer|main)\b", c))
    if sections >= 3:
        return True
    body = re.sub(r"<script[\s\S]*?</script>", "", c, flags=re.I)
    body = re.sub(r"<style[\s\S]*?</style>", "", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    words = len([w for w in re.split(r"\s+", body) if w.strip()])
    return words >= 80


def extract_requirements(task: str, max_items: int = 16) -> list[str]:
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
        owner = m.group(1).rstrip("._-")  # sin puntuación de cierre de frase
        if owner:
            owners.add(owner)
    for owner in sorted(owners):
        base = f"github.com/{owner}"
        if not any(f"{base}/" in r for r in reqs) and base not in reqs:
            reqs.append(base)

    # 3) nombres de repos en PascalCase (se exige que aparezcan en el código)
    if owners:
        seen = set()
        skip = {"HTML", "CSS", "JS", "GitHub", "Python", "JavaScript", "TypeScript",
                "Landing", "Portfolio", "LandingPage", "Vicente", "Vila", "VicenteVila",
                "Repo", "Repos", "Cada", "Para", "Con", "Sin", "Una", "Un", "Los", "Las",
                "Son", "Web", "Enfoque", "Diseño", "Diseños", "Estética", "Visual",
                "Visuales", "Interactivos", "Interactivo", "Interactivas", "Interactiva",
                "Moderno", "Modernos", "Actuales", "Actual", "Tarea", "Proyecto",
                "Proyectos", "Página", "Pagina", "Páginas", "Paginas", "Contenido",
                "Sección", "Seccion", "Secciones", "Tiene", "Debe", "Deben", "Más",
                "Mas", "Todo", "Todos", "Primer", "Segundo", "Tercer", "Uso", "Usa",
                "Usar", "Lista", "Listado", "Nombre", "Nombres", "Descripción",
                "Descripcion", "Lenguaje", "Etiqueta", "Etiquetas", "Categoría",
                "Categoria", "Categorías", "Categorias", "Perfil", "Cuenta", "Usuario",
                "Usuarios", "Repositorio", "Repositorios", "Biblioteca", "Bibliotecas",
                "Librería", "Librerias", "Agente", "Agentes", "AgentesIA", "IA", "GenAI",
                "AI", "OpenAI", "Gemini", "Groq", "Ollama", "Langfuse",
                "Crea", "Grafo", "GRAFO", "GrafoDe", "Conocimiento", "Conocimientos",
                "CONOCIMIENTOS", "SVG", "Nodo", "Nodos", "Subnodo", "Subnodos",
                "Hover", "Hovers", "Documentación", "Documentacion", "Documento",
                "Documentos", "CategoríasSujet", "Sujet", "Sujetos", "TRES", "Tres",
                "Esos", "Esas", "Incluye", "Incluyen", "Dise", "Diseño", "Descripción",
                "Enlace", "Enlaces", "Muestra", "Muestran", "Expandido", "Expandidos",
                "Expansión", "Expansion", "Leyenda", "Footer", "Dark", "Light",
                "Local", "Locales", "Ruta", "Rutas", "PáginaLocal", "PaginaLocal",
                "MEJORA", "Mejora", "TICA", "Estetica", "Estética", "MUTA", "Muta",
                "SIEMPRE", "Siempre", "CORRECCIONES", "Correcciones", "Exigidas",
                "Exigidos", "DIBUJA", "Dibuja", "ENLAZA", "Enlaza", "AUMENTA",
                "Aumenta", "DISTRIBUYE", "Distribuye", "FEEDBACK", "REQUISITOS",
                "Requisitos", "REQUISITO", "Requisito", "CONSERVA", "Conserva",
                "EXIGIDAS", "Exigida", "ARISTAS", "Aristas", "VISIBLES", "Visibles",
                "Nada", "NADA", "Crítico", "Critico", "Diseñador", "Disenador",
                "Screenshot", "screenshot", "VLM", "Vlm", "LEGIBILIDAD", "Legibilidad",
                "HOVER", "DISE", "Storage", "LocalStorage", "Localstorage",
                "Despu", "Despues", "Después", "Verificar", "Detectó", "Detecto",
                "Resolvieron", "Resuelto", "Resueltos", "Fallo", "Fallos",
                "Críticos", "Criticos", "Detectados", "generar", "GENERE",
                "Escala", "Reduce", "JERARQU", "VISUAL", "Jerarqu", "Jerarquía",
                "Jerarquia", "Contraste", "Peso", "Bold", "Negro", "Blanco",
                "ESTRUCTURALES", "FINALES", "DEBE", "Data", "Documentaci",
                "Documentación", "Documentacion", "DERECHA", "Derecha",
                "NUNCA", "Nunca", "Casing", "Repítelas", "Repitelas",
                "regen", "Regen", "regenera", "Regenera", "Title", "Case",
                "Evoluci", "Evolución", "Evolucion", "Readaptaci",
                "Readaptación", "Readaptacion", "Razonamiento", "Size", "Font",
                "FontSize", "Text"}
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


# Secciones estructurales típicas que puede exigir una tarea. Cada entrada es
# (clave, [alias/keywords a detectar en el HTML]).
SECTION_ALIASES = {
    "navbar": ["navbar", "nav-links", "<nav", "header-nav", "topnav", "barra de navegacion", "menu de navegacion"],
    "hero": ["hero", "cta-group", "hero-title", "jumbotron", "portada", "titulo principal"],
    "graph": ["graph", "grafo", "knowledge-graph", "svg-graph", "nodes", "nodos", "network", "grafo de conocimientos", "conocimientos"],
    "root_node": ["root-node", "nodo central", "nodo raiz", "root", "raiz", "central node", "center node"],
    "readme": ["readme", "repos/", "repositorios", "local readme"],
    "topics": ["topics", "arxiv", "categorias", "categorias sujet", "cs.ai", "cs.lg", "cs.cl"],
    "docs": ["docs", "evolucion", "readaptacion", "reasoning", "documentacion", "readaptation", "evolution", "doc subnodes", "subnodos de docs"],
    "logo_bar": ["logo-bar", "trusted", "logos", "trusted-by", "logo bar", "marcas", "logo bar 'trusted by'"],
    "stats": ["stats", "stat-card", "counter", "metrics", "metricas", "contadores", "estadisticas"],
    "features": ["features", "feature-card", "feature-grid", "cards", "grid", "beneficios", "tarjetas", "caracteristicas"],
    "integrations": ["integrations", "integration", "tool-stack", "integrations-grid", "stack", "integraciones", "tool stack", "herramientas"],
    "social_proof": ["social-proof", "testimonial", "testimonials", "case-study", "reviews", "case-studies", "social proof", "prueba social", "casos de exito"],
    "faq": ["faq", "accordion", "accordeon", "preguntas", "preguntas frecuentes"],
    "cta": ["cta", "cta-final", "cta-section", "call-to-action", "llamada a la accion", "cta final"],
    "footer": ["footer", "<footer", "pie de pagina"],
    "testimonial": ["testimonial", "testimonials", "case-study", "reviews", "testimonios"],
    "contact": ["contact", "contacto", "contact-form", "formulario de contacto"],
    "pricing": ["pricing", "precios", "price-card", "plans", "planes", "tarifas"],
    "about": ["about", "acerca", "nosotros", "acerca de"],
}


def extract_sections(task: str) -> list[str]:
    """Extrae de la tarea las secciones estructurales que se exigen, en orden.

    Busca menciones de secciones típicas (navbar, hero, stats, FAQ, footer, etc.)
    en el texto de la tarea y devuelve sus claves canónicas. Si la tarea no
    menciona ninguna sección, devuelve una lista vacía (no se evalúa structure).
    """
    task_low = task.lower()
    found: list[str] = []
    # orden preferente para que el prompt/score sea estable
    priority = ["navbar", "hero", "graph", "root_node", "readme", "topics", "docs",
                "logo_bar", "stats", "features", "integrations",
                "social_proof", "testimonial", "faq", "cta", "footer", "contact",
                "pricing", "about"]
    for key in priority:
        aliases = SECTION_ALIASES[key]
        # si la tarea menciona un alias relevante de esa sección
        if any(a in task_low for a in aliases):
            # evitar duplicar alias genéricos ('grid', 'stack', 'cards')
            if key not in found:
                found.append(key)
    return found


def _html_has_section(h: str, key: str) -> bool:
    """Comprueba que la sección estructural 'key' aparece en el HTML.

    Busca id="...key..." / class="...key..." o cualquiera de sus alias
    (case-insensitive) dentro del HTML, para no depender solo de nombres exactos.
    """
    h_low = h.lower()
    aliases = SECTION_ALIASES.get(key, [key])
    for a in aliases:
        if a in h_low:
            return True
    return False


WEIGHTS = {
    "seo": 1.0,
    "a11y": 1.0,
    "performance": 1.0,
    "responsive": 1.0,
    "best_practices": 1.0,
    "visual": 2.0,
    "structure": 2.0,
    "functional": 1.0,
    "task": 1.0,
}


def _apply_blocking_gates(total: int, gates: dict, ceiling: int = None) -> int:
    """Capa el total si algún gate bloqueante está activo (Eq. 8 del paper:
    un P0 gate impone un techo a la puntuación aunque el resto de ejes puntúe alto)."""
    if not gates:
        return total
    from config import BLOCKING_CEILING
    cap = ceiling if ceiling is not None else BLOCKING_CEILING
    return min(total, cap)


def evaluate(project_dir: str | Path, requirements: list[str] | None = None, weights: dict | None = None,
             structure: list[str] | None = None, run_functional: bool = True) -> dict:
    """Evalúa un proyecto web estático. Devuelve métricas por categoría y total.

    requirements: lista de subcadenas que DEBEN aparecer en el código (html+css+js)
    concatenado. Si se pasan, se añade la categoría 'task' al total (requisitos de
    la tarea estipulada presentes). Si no, 'task' se ignora.

    structure: lista de secciones obligatorias (id, clase o palabra clave) que deben
    estar presentes en el HTML de la raíz. Si se pasa, se añade la categoría
    'structure' al total (peso 2.0). Ver extract_sections().

    IMPORTANTE: solo se evalúan archivos en la RAÍZ del proyecto (index.html,
    styles.css, app.js). Los subdirectorios (repos/, assets/, etc.) NO participan
    en ningún contexto de evaluación para evitar inflar métricas con contenido
    auxiliar.

    'visual' es un proxy de diseño moderno/interactivo que exige efectos REALES
    (canvas con requestAnimationFrame+dibujo DINÁMICO, @keyframes usado, gradientes
    en propiedades, transition con disparador, etc.), no solo menciones.

    total = media PONDERADA de las categorías (WEIGHTS; visual y structure pesan
    2.0 por defecto). Se puede sobrescribir con weights=.
    """
    project_dir = Path(project_dir)
    html_files = sorted(project_dir.glob("*.html"))
    css_text = " ".join(p.read_text(errors="replace") for p in project_dir.glob("*.css"))
    js_text = " ".join(p.read_text(errors="replace") for p in project_dir.glob("*.js"))

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

    # Categoría 'structure': secciones obligatorias presentes en el HTML de la raíz.
    structure = structure or []
    structure_fails = [s for s in structure if not _html_has_section(h, s)]
    structure_score = int(100 * (len(structure) - len(structure_fails)) / len(structure)) if structure else None

    # Categoría 'functional': el candidato DEBE ser funcional de verdad (no solo
    # parecerlo). Se ejecuta un test funcional real en Chrome headless: clicks,
    # submits, enlaces internos, errores JS. Si el test no puede ejecutarse
    # (Chrome ausente) el eje queda None y NO penaliza (gate solo con evidencia).
    # run_functional=False permite aislar el blend (tests unitarios del evaluador).
    functional = None
    functional_fails: list[str] = []
    if run_functional:
        try:
            from tools.domain.functional_tester import run_functional_test
            _ft = run_functional_test(html_files[0])
            if _ft.get("ok") and _ft.get("functional") is not None:
                functional = _ft["functional"]
                functional_fails = [
                    f"[{t.get('n')}] {t.get('d')}" for t in _ft.get("tests", [])
                    if t.get("p") != 1
                ]
        except Exception:
            functional = None

    html_bytes = sum(p.stat().st_size for p in html_files)
    css_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.css"))
    js_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.js"))
    img_bytes = sum(p.stat().st_size for p in project_dir.rglob("*")
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"))

    axes = {"seo": seo, "a11y": a11y, "performance": perf, "responsive": resp, "best_practices": bp, "visual": visual}
    if task is not None:
        axes["task"] = task
    if structure_score is not None:
        axes["structure"] = structure_score
    if functional is not None:
        axes["functional"] = functional
    w = {**WEIGHTS, **(weights or {})}
    num = sum(axes[k] * w.get(k, 1.0) for k in axes)
    den = sum(w.get(k, 1.0) for k in axes)
    total = int(num / den) if den else 0

    # GATES BLOQUEANTES (anti-trampa ejecutable, no solo prompt). Un candidato
    # que omite secciones obligatorias de la tarea queda CAPADO por encima, aunque
    # el resto de ejes puntúe alto. La estructura es gate P0: ceiling = 40.
    gates: dict[str, list[str]] = {}
    if structure_fails:
        gates["structure"] = structure_fails

    # GATE FUNCIONAL (P0): si el candidato no es funcional de verdad (JS roto,
    # interactivos sin efecto, enlaces rotos, formularios que recargan), queda
    # capado igual que un candidato sin secciones. "Primero funcional, luego
    # bonito": la estética nunca compensa una página que no funciona.
    if functional is not None and functional < 60:
        gates["functional"] = functional_fails or [f"test funcional fallido ({functional}/100)"]

    # GATE DE PARTES INTEGRANTES: si el candidato fabrica repos/ pero NO los
    # enlaza desde la raíz (repos huérfanos), queda capado igual que un candidato
    # sin secciones obligatorias. Un HTML fabricado y desconectado no es válido.
    repos_dir = project_dir / "repos"
    if repos_dir.is_dir():
        linked = set(
            re.findall(r'href=["\']([^"\']*repos/[^"\']*index\.html)["\']', h)
        )
        repo_dirs = sorted(
            p for p in repos_dir.iterdir()
            if p.is_dir() and (p / "index.html").exists()
        )
        orphan = [
            p.name for p in repo_dirs
            if f"repos/{p.name}/index.html" not in linked
        ]
        if orphan:
            gates["parts_connected"] = [
                f"repos huérfanos (fabricados pero NO enlazados): {', '.join(orphan[:5])}"
            ]

    total = _apply_blocking_gates(total, gates)

    return {
        "total": total,
        "seo": seo,
        "a11y": a11y,
        "performance": perf,
        "responsive": resp,
        "best_practices": bp,
        "visual": visual,
        "task": task,
        "structure": structure_score,
        "functional": functional,
        "gates": gates,
        "failures": {
            "seo": seo_fails,
            "a11y": a11y_fails,
            "performance": perf_fails,
            "responsive": resp_fails,
            "best_practices": bp_fails,
            "visual": visual_fails,
            "task": task_fails,
            "structure": structure_fails,
            "functional": functional_fails,
        },
        "files": {
            "html": n_html,
            "total_html_kb": round(html_bytes / 1024, 1),
            "total_css_kb": round(css_bytes / 1024, 1),
            "total_js_kb": round(js_bytes / 1024, 1),
            "total_img_kb": round(img_bytes / 1024, 1),
        },
    }


def blend_visual_total(metrics: dict, vlm: int | None, weights: dict | None = None) -> int | None:
    """Recombina el total de un nodo cuando llega la crítica VLM estética.

    El axis 'visual' (proxy estático) se sustituye por la mejor señal disponible:
    si hay score VLM real, se usa max(visual_estatico, vlm). Así la búsqueda
    recompensa mejoras estéticas reales (Eq. AutoDesign: feedback P0 guía la
    siguiente mutación) en lugar de ignorarlas. Devuelve None si no hay total.
    """
    total = metrics.get("total")
    if total is None:
        return None
    if vlm is None:
        return total
    visual_static = metrics.get("visual") or 0
    axes = {
        "seo": metrics.get("seo"),
        "a11y": metrics.get("a11y"),
        "performance": metrics.get("performance"),
        "responsive": metrics.get("responsive"),
        "best_practices": metrics.get("best_practices"),
        "visual": max(visual_static, vlm),
    }
    for key in ("task", "structure", "functional"):
        if metrics.get(key) is not None:
            axes[key] = metrics[key]
    w = {**WEIGHTS, **(weights or {})}
    num = sum(axes[k] * w.get(k, 1.0) for k in axes)
    den = sum(w.get(k, 1.0) for k in axes)
    blended = int(num / den) if den else 0
    gates = metrics.get("gates") or {}
    if gates:
        blended = _apply_blocking_gates(blended, gates)
    return blended