"""Tests del evaluador ligero."""
from __future__ import annotations

from pathlib import Path

from tools.domain.evaluator import evaluate

GOOD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Corto</title>
<meta name="description" content="description">
<meta property="og:title" content="Corto">
<link rel="canonical" href="https://example.com/">
</head>
<body>
<main><section><h1>Único</h1><img src="a.webp" alt="x" width="100" height="100"></section></main>
<a class="skip-link" href="#main">Skip</a>
<nav aria-label="x"><ul><li><a href="/">Home</a></li></ul></nav>
</body>
</html>"""

BAD_HTML = """<html>
<head><title>Un título extremadamente largo que supera los sesenta caracteres de límite permitido por SEO</title></head>
<body><div><h1>Primero</h1><h1>Segundo</h1><img src="foto.jpg"><input type="text"></div></body></html>"""


def _write(case: dict, name: str) -> Path:
    d = Path("/tmp/opencode") / f"fixture_{name}"
    d.mkdir(parents=True, exist_ok=True)
    for fname, content in case.items():
        p = d / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return d


def test_good_scores_high():
    css = """body{background:linear-gradient(90deg,#fff,#ddd)}
    nav{position:sticky;top:0}
    @keyframes fade{from{opacity:0}to{opacity:1}}
    .card{transition:transform .2s}.card:hover{transform:scale(1.02);animation:fade 1s}
    @media (prefers-color-scheme:dark){body{background:#111}}
    @media (prefers-reduced-motion:reduce){*{animation:none}}
    """
    html = GOOD_HTML + '<canvas id="c"></canvas><script>const io=new IntersectionObserver(()=>{});</script>'
    js = 'const c=document.getElementById("c").getContext("2d");function a(){c.fillRect(Math.random()*100,Math.random()*100,3,3);requestAnimationFrame(a)}a();'
    d = _write({"index.html": html, "styles.css": css, "app.js": js}, "good")
    m = evaluate(d)
    assert m["total"] >= 75, m
    assert m["seo"] >= 70, m
    assert m["visual"] >= 70, m


def test_bad_scores_low():
    d = _write({"index.html": BAD_HTML}, "bad")
    m = evaluate(d)
    assert m["total"] <= 60, m
    assert "h1" in m["failures"]["seo"]


def test_modern_images_detected():
    html = '<img src="hero.webp" alt="h" width="100" height="100">'
    d = _write({"index.html": f"<!DOCTYPE html><html><body>{html}</body></html>"}, "webp")
    m = evaluate(d)
    assert "modern_img" not in m["failures"]["performance"]


def test_task_requirements_present():
    html = """<!DOCTYPE html><html><body>
    <h1>Repos</h1><script>const repos=[{name:'TraceForge',url:'https://github.com/VicenteVila/TraceForge'}];</script>
    </body></html>"""
    d = _write({"index.html": html, "app.js": ""}, "task_ok")
    m = evaluate(d, requirements=["TraceForge", "github.com/VicenteVila/TraceForge"])
    assert m["task"] == 100, m
    assert "task" in m["failures"]


def test_task_requirements_missing():
    html = """<!DOCTYPE html><html><body><h1>Repos</h1>
    <script>const repos=[{name:'TraceForge'}];</script></body></html>"""
    d = _write({"index.html": html, "app.js": ""}, "task_bad")
    m = evaluate(d, requirements=["TraceForge", "github.com/VicenteVila/TraceForge"])
    assert m["task"] == 50, m
    assert "github.com/VicenteVila/TraceForge" in m["failures"]["task"]


def test_task_absent_ignored():
    d = _write({"index.html": GOOD_HTML, "styles.css": "body{}", "app.js": ""}, "task_none")
    m = evaluate(d, run_functional=False)  # sin requirements
    assert m["task"] is None, m
    assert m["visual"] is not None, m
    # total ponderado con visual 2.0x
    axes = {
        "seo": m["seo"], "a11y": m["a11y"], "performance": m["performance"],
        "responsive": m["responsive"], "best_practices": m["best_practices"], "visual": m["visual"],
    }
    from tools.domain.evaluator import WEIGHTS
    num = sum(axes[k] * WEIGHTS[k] for k in axes)
    den = sum(WEIGHTS[k] for k in axes)
    assert m["total"] == int(num / den), m


def test_weighted_total_visual_dominates():
    """Con visual=0 vs visual=100, el total ponderado se mueve más por visual."""
    from tools.domain.evaluator import WEIGHTS
    assert WEIGHTS["visual"] == 2.0
    base = {"seo": 90, "a11y": 90, "performance": 90, "responsive": 90, "best_practices": 90, "visual": 50}
    lo = {**base, "visual": 0}
    hi = {**base, "visual": 100}
    def tot(axes):
        num = sum(axes[k] * WEIGHTS[k] for k in axes)
        return int(num / sum(WEIGHTS[k] for k in axes))
    assert hi["visual"] - lo["visual"] == 100
    assert tot(hi) - tot(lo) >= 25, (tot(hi), tot(lo))


def test_visual_high_with_modern_design():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><header></header><nav></nav><main><section><h1>Único</h1>
    <p>Texto de contenido real para la página</p></section><section><p>Segunda sección</p></section></main>
    <canvas id="c"></canvas>
    <script>const io=new IntersectionObserver(()=>{});</script></body></html>"""
    css = """body{background:linear-gradient(90deg,#000,#333)}
    nav{position:sticky;top:0}
    @keyframes fade{from{opacity:0}to{opacity:1}}
    .card{transition:transform .2s}
    .card:hover{transform:scale(1.05);animation:fade 1s}
    .btn:focus{outline:2px solid #fff;transition:outline .2s}
    @media (prefers-color-scheme:dark){body{background:#111}}
    @media (prefers-reduced-motion:reduce){*{animation:none}}
    """
    js = ('const c=document.getElementById("c").getContext("2d");'
          'function a(){c.fillRect(Math.random()*99,Math.random()*99,2,2);requestAnimationFrame(a)}a();'
          'const t=localStorage.getItem("theme");document.body.classList.toggle("dark",t==="dark");')
    d = _write({"index.html": html, "styles.css": css, "app.js": js}, "visual_high")
    m = evaluate(d)
    assert m["visual"] >= 90, m
    assert "css_animations" not in m["failures"]["visual"]
    assert "canvas_animated" not in m["failures"]["visual"]


def test_visual_low_with_plain_page():
    d = _write({"index.html": GOOD_HTML, "styles.css": "body{color:black}", "app.js": ""}, "visual_low")
    m = evaluate(d)
    assert m["visual"] <= 30, m


def test_canvas_declared_but_not_animated_fails():
    """Canvas presente pero sin requestAnimationFrame+dibujo = fallo visual."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><main><h1>Único</h1></main><canvas id="c"></canvas></body></html>"""
    js = 'const c=document.getElementById("c");c.getContext("2d");c.width=innerWidth;'
    d = _write({"index.html": html, "styles.css": "body{}", "app.js": js}, "canvas_dead")
    m = evaluate(d)
    assert "canvas_animated" in m["failures"]["visual"], m
    assert "no_dead_canvas" in m["failures"]["visual"], m


def test_no_canvas_is_not_penalized():
    """Página sin canvas no debe fallar no_dead_canvas."""
    d = _write({"index.html": GOOD_HTML, "styles.css": "body{}", "app.js": ""}, "no_canvas")
    m = evaluate(d)
    assert "no_dead_canvas" not in m["failures"]["visual"], m


def test_gradient_in_comment_not_counted():
    css = "/* background:linear-gradient(90deg,#fff,#000); */ body{color:black}"
    d = _write({"index.html": GOOD_HTML, "styles.css": css, "app.js": ""}, "grad_comment")
    m = evaluate(d)
    assert "gradients" in m["failures"]["visual"], m


def test_transition_without_trigger_not_counted():
    css = ".x{transition:all .3s}"
    d = _write({"index.html": GOOD_HTML, "styles.css": css, "app.js": ""}, "trans_notrig")
    m = evaluate(d)
    assert "css_transitions" in m["failures"]["visual"], m


def test_extract_requirements_ignores_placeholders():
    from tools.domain.evaluator import extract_requirements
    reqs = extract_requirements("Enlace a https://github.com/VicenteVila/<repo> y github.com/VicenteVila")
    assert not any("<repo>" in r for r in reqs), reqs
    assert "github.com/VicenteVila" in reqs, reqs


def test_extract_requirements_skips_spanish_noise():
    from tools.domain.evaluator import extract_requirements
    reqs = extract_requirements(
        "Diseño visual vanguardista para repos de github.com/VicenteVila: TraceForge y CogniTeam con Enfoque estético"
    )
    assert "Enfoque" not in reqs, reqs
    assert "TraceForge" in reqs, reqs
    assert "CogniTeam" in reqs, reqs


def test_responsive_checks_external_css():
    """media_queries/flexgrid se evalúan contra el CSS externo, no solo el HTML."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><main><h1>Único</h1></main></body></html>"""
    css = "@media (max-width:600px){.x{display:block}} .grid{display:grid}"
    d = _write({"index.html": html, "styles.css": css}, "resp_css")
    m = evaluate(d)
    assert "media_queries" not in m["failures"]["responsive"], m
    assert "flexgrid" not in m["failures"]["responsive"], m


def test_charset_uppercase_ok():
    html = '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"><title>Corto</title></head><body><h1>Único</h1></body></html>'
    d = _write({"index.html": html}, "charset_upper")
    m = evaluate(d)
    assert "charset" not in m["failures"]["best_practices"], m


def test_structure_present_scores_high():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body>
    <nav class="navbar"><a href="#features">Agentes</a></nav>
    <section class="hero"><h1>Único</h1></section>
    <section class="logo-bar"><span>Trusted by</span></section>
    <section id="stats" class="stats"><div class="stat-card">+30%</div></section>
    <section id="features" class="grid"><div class="feature-card">Card</div></section>
    <section id="integrations"><div>Stack</div></section>
    <section class="testimonial"><blockquote>Genial</blockquote></section>
    <section id="faq" class="accordion"><details><summary>Q</summary></details></section>
    <a class="cta" href="#contact">CTA</a>
    <footer><p>© 2024</p></footer>
    </body></html>"""
    d = _write({"index.html": html}, "struct_ok")
    m = evaluate(d, structure=["navbar", "hero", "logo_bar", "stats", "features",
                               "integrations", "social_proof", "faq", "cta", "footer"])
    assert m["structure"] == 100, m
    assert "structure" in m["axes"] if "axes" in m else True
    assert "structure" in m["failures"] and not m["failures"]["structure"]


def test_structure_missing_lowers_total():
    """Landing minimalista con tokens pero sin secciones obligatorias: structure baja."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><nav class="navbar"></nav><section class="hero"><h1>Único</h1></section>
    <section class="features"><div class="card">x</div></section><footer></footer></body></html>"""
    d = _write({"index.html": html}, "struct_minimal")
    m = evaluate(d, structure=["navbar", "hero", "logo_bar", "stats", "features",
                               "integrations", "social_proof", "faq", "cta", "footer"])
    assert m["structure"] <= 60, m
    assert "logo_bar" in m["failures"]["structure"]
    assert "integrations" in m["failures"]["structure"]


def test_blocking_gate_caps_total_when_sections_missing():
    """Anti-trampa ejecutable: si faltan secciones obligatorias, el total queda
    CAPADO por el ceiling (P0 gate, Eq. 8 del paper) aunque el resto puntúe alto."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title>
    <meta name="description" content="desc">
    <meta property="og:title" content="Corto"><link rel="canonical" href="https://e.com/">
    <link rel="preload" as="image" href="x.webp">
    </head>
    <body><main><section><h1>Único</h1><img src="a.webp" alt="x" width="100" height="100"></section></main>
    <a class="skip-link" href="#main">Skip</a><nav aria-label="x"><ul><li><a href="/">Home</a></li></ul></nav>
    <style>@keyframes pulse{from{opacity:1}to{opacity:.5}} .x{animation:pulse 2s infinite}</style>
    <script>const c=document.createElement('canvas');document.body.appendChild(c);
    const ctx=c.getContext('2d');function f(){ctx.fillRect(Math.random()*10,0,2,2);requestAnimationFrame(f)}f();</script>
    </body></html>"""
    d = _write({"index.html": html}, "gate_missing_sections")
    m = evaluate(d, structure=["navbar", "hero", "logo_bar", "stats", "features",
                               "integrations", "social_proof", "faq", "cta", "footer"])
    # pese a checks técnicos altos, el gate capa el total
    assert "structure" in m["gates"] and m["gates"]["structure"]
    assert m["total"] <= 40, m["total"]
    # pero los ejes por separado no se degradan por el gate
    assert m["seo"] > 60


def test_blocking_gate_inactive_when_all_sections_present():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body>
    <nav class="navbar"></nav><section class="hero"><h1>Único</h1></section>
    <section class="logo-bar"></section><section id="stats"></section>
    <section id="features"></section><section id="integrations"></section>
    <section class="testimonial"></section><section id="faq"></section>
    <a class="cta" href="#cta"></a><footer></footer></body></html>"""
    d = _write({"index.html": html}, "gate_all_sections")
    m = evaluate(d, structure=["navbar", "hero", "logo_bar", "stats", "features",
                               "integrations", "social_proof", "faq", "cta", "footer"])
    assert not m["gates"], m["gates"]
    assert m["structure"] == 100


def test_subdir_not_evaluated():
    """Archivos HTML/CSS/JS en subdirectorios NO inflan el contexto de evaluación."""
    html_root = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title>
    <meta name="description" content="desc"></head>
    <body><main><section><h1>Único</h1></section></main>
    <a class="skip-link" href="#main">Skip</a><nav><ul><li><a href="/">Home</a></li></ul></nav>
    </body></html>"""
    sub_html = """<!DOCTYPE html><html lang="en"><head><title>Sub</title></head>
    <body><div><h1>No cuenta</h1><h1>Segundo</h1></div></body></html>"""
    sub_css = "@media (max-width:600px){.x{display:block}} .grid{display:grid}"
    sub_js = "console.log('hola');"
    d = _write({"index.html": html_root,
                "sub/index.html": sub_html,
                "sub/styles.css": sub_css,
                "sub/app.js": sub_js}, "subdir")
    m = evaluate(d)
    # el subdir no debe aportar: sigue fallando flexgrid/media si la raíz no lo tiene
    assert "flexgrid" in m["failures"]["responsive"], m
    # y el console.log del subdir no debe contar como fallo de la página
    assert "no_console" not in m["failures"]["best_practices"], m
    # y no debe haber múltiples h1 por culpa del subdir
    assert "h1" not in m["failures"]["seo"], m


def test_static_canvas_fails_animated():
    """fillRect estático en bucle (mismas coordenadas) NO cuenta como canvas animado."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><main><h1>Único</h1></main><canvas id="c"></canvas></body></html>"""
    js = ('const c=document.getElementById("c").getContext("2d");'
          'function a(){c.fillRect(0,0,100,100);requestAnimationFrame(a)}a();')
    d = _write({"index.html": html, "app.js": js}, "canvas_static")
    m = evaluate(d)
    assert "canvas_animated" in m["failures"]["visual"], m
    assert "no_dead_canvas" in m["failures"]["visual"], m


def test_dynamic_canvas_passes():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><main><h1>Único</h1></main><canvas id="c"></canvas></body></html>"""
    js = ('const c=document.getElementById("c").getContext("2d");'
          'let x=0;function a(){x++;c.fillRect(x%400,50,5,5);requestAnimationFrame(a)}a();')
    d = _write({"index.html": html, "app.js": js}, "canvas_dyn")
    m = evaluate(d)
    assert "canvas_animated" not in m["failures"]["visual"], m


def test_tailwind_classes_accepted_for_flexgrid():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><main><h1>Único</h1></main>
    <div class="grid md:grid-cols-3 gap-8"><div class="flex">x</div></div></body></html>"""
    d = _write({"index.html": html}, "tailwind")
    m = evaluate(d)
    assert "flexgrid" not in m["failures"]["responsive"], m


def test_cdn_framework_penalized():
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><h1>Único</h1><script src="https://cdn.tailwindcss.com"></script></body></html>"""
    d = _write({"index.html": html}, "cdn")
    m = evaluate(d)
    assert "no_cdn" in m["failures"]["best_practices"], m


def test_extract_sections_from_task():
    from tools.domain.evaluator import extract_sections
    s = extract_sections("navbar sticky, hero, stats con contadores, features grid, FAQ acordeón, footer")
    assert "navbar" in s and "hero" in s and "stats" in s and "features" in s and "faq" in s and "footer" in s
    assert s == ["navbar", "hero", "stats", "features", "faq", "footer"], s


def test_extract_sections_graph_task():
    from tools.domain.evaluator import extract_sections
    s = extract_sections(
        "grafo de conocimientos con nodo central (Vicente Vila), repositorios que "
        "abren su readme local (repos/) y categorias sujet arXiv (cs.AI, cs.LG)"
    )
    assert "graph" in s, s
    assert "root_node" in s, s
    assert "readme" in s, s
    assert "topics" in s, s


def test_graph_structure_present_scores_high():
    """Un grafo SVG con nodo raíz, repos, enlaces README local y categorías arXiv pasa structure."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body>
    <nav class="navbar"><a href="#graph">Grafo</a></nav>
    <section class="hero"><h1>Vicente Vila</h1></section>
    <section id="graph" class="knowledge-graph">
      <svg id="svg-graph"><g class="node root-node"><title>Vicente Vila</title></g>
      <g class="node repo"><title>TraceForge</title><a href="repos/TraceForge/index.html">README</a></g></svg>
    </section>
    <section id="topics"><span class="arxiv">cs.AI</span><span>cs.LG</span></section>
    <a class="cta" href="#contact">Contacto</a>
    <footer><p>© 2026</p></footer>
    </body></html>"""
    d = _write({"index.html": html}, "graph_ok")
    m = evaluate(d, structure=["navbar", "hero", "graph", "root_node", "readme", "topics", "cta", "footer"])
    assert m["structure"] == 100, m
    assert not m["failures"]["structure"], m


def test_graph_structure_missing_lowers():
    """Grafo sin nodo raíz ni enlaces README local ni categorías: estructura incompleta."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body><section id="graph"><svg><circle></circle></svg></section></body></html>"""
    d = _write({"index.html": html}, "graph_missing")
    m = evaluate(d, structure=["graph", "root_node", "readme", "topics"])
    assert m["structure"] <= 40, m
    for key in ("root_node", "readme", "topics"):
        assert key in m["failures"]["structure"], key


def test_extract_sections_no_noise_from_repo_names():
    from tools.domain.evaluator import extract_sections
    s = extract_sections("landing para CogniTeam y equipos de agentes IA")
    assert "about" not in s, s


def test_extract_sections_docs_task():
    """Una tarea que menciona docs de ReaWeb (EVOLUTION/READAPTATION/REASONING)
    debe activar la sección 'docs'."""
    from tools.domain.evaluator import extract_sections
    s = extract_sections(
        "grafo de conocimientos con repositorios y subnodos de docs (EVOLUTION, "
        "READAPTATION, REASONING) visibles de ReaWeb"
    )
    assert "graph" in s, s
    assert "docs" in s, s


def test_graph_structure_docs_present_scores_high():
    """Grafo con docs de ReaWeb enlazando a repos/ReaWeb/docs/<name>/index.html pasa structure."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body>
    <nav class="navbar"><a href="#graph">Grafo</a></nav>
    <section class="hero"><h1>Vicente Vila</h1></section>
    <section id="graph" class="knowledge-graph">
      <svg id="svg-graph"><g class="node root-node"><title>Vicente Vila</title></g>
      <g class="node repo"><title>TraceForge</title><a href="repos/TraceForge/index.html">README</a></g>
      <g class="node repo docs"><title>ReaWeb</title>
        <a class="doc-link" href="repos/ReaWeb/docs/EVOLUTION/index.html">EVOLUTION</a>
        <a class="doc-link" href="repos/ReaWeb/docs/READAPTATION/index.html">READAPTATION</a>
        <a class="doc-link" href="repos/ReaWeb/docs/REASONING/index.html">REASONING</a></g></svg>
    </section>
    <section id="topics"><span class="arxiv">cs.AI</span><span>cs.LG</span></section>
    <section id="docs"><p>Documentación</p></section>
    <a class="cta" href="#contact">Contacto</a>
    <footer><p>© 2026</p></footer>
    </body></html>"""
    d = _write({"index.html": html}, "graph_docs_ok")
    m = evaluate(d, structure=["navbar", "hero", "graph", "root_node", "readme", "topics", "docs", "cta", "footer"])
    assert m["structure"] == 100, m
    assert not m["failures"]["structure"], m


def test_graph_structure_docs_missing_lowers():
    """Grafo sin docs de ReaWeb: la sección 'docs' falla (resto de secciones ok)."""
    html = """<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1"><title>Corto</title></head>
    <body>
    <section id="graph"><svg><g class="node root-node"><title>Vicente Vila</title></g>
    <g class="node repo"><title>TraceForge</title><a href="repos/TraceForge/index.html">README</a></g></svg></section>
    <section id="topics"><span class="arxiv">cs.AI</span></section>
    <footer><p>© 2026</p></footer>
    </body></html>"""
    d = _write({"index.html": html}, "graph_docs_missing")
    m = evaluate(d, structure=["graph", "root_node", "readme", "topics", "docs"])
    assert "docs" in m["failures"]["structure"], m
    assert m["structure"] < 100, m


def test_visual_low_when_static_canvas_and_plain():
    """Página plana sin canvas dinámico ni secciones no debe alcanzar visual alto."""
    d = _write({"index.html": GOOD_HTML, "styles.css": "body{color:black}", "app.js": ""}, "visual_low2")
    m = evaluate(d)
    assert m["visual"] <= 30, m

# --- F1: loop de subtareas ---
from tools.domain.evaluator import extract_subtasks, subtasks_status, format_subtasks_status, novelty_score
from tools.domain.web_generator import GenerateCandidate

PORTFOLIO_TASK = (
    "Portfolio creativo con navbar, hero, stats, features, testimonial, faq, cta, "
    "footer, contact, about y filtros de proyectos que funcionan"
)


def test_extract_subtasks_includes_structure_func_and_literal():
    subs = extract_subtasks(PORTFOLIO_TASK)
    tipos = {s["tipo"] for s in subs}
    ids = [s["id"] for s in subs]
    assert "estructural" in tipos and "funcional" in tipos
    assert "seccion:navbar" in ids and "funcional:js_sin_errores" in ids
    # cada subtarea tiene criterio de aceptación verificable
    for s in subs:
        assert s["id"] and s["cheque"], s


def test_subtasks_status_marks_missing_section_and_broken_functional():
    html = """
    <html><body><header id="navbar"><nav><a href="#hero">H</a></nav></header>
    <section id="hero"><h1>Hola</h1></section></body></html>"""
    st = subtasks_status(html, "", "", PORTFOLIO_TASK, None)
    assert st["seccion:navbar"]["ok"] is True
    assert st["seccion:hero"]["ok"] is True
    assert st["seccion:faq"]["ok"] is False, st  # no hay FAQ en el HTML
    # funcionales sin test ejecutado -> FAIL informativo
    assert st["funcional:js_sin_errores"]["ok"] is False
    assert "no ejecutado" in st["funcional:js_sin_errores"]["detail"]


def test_subtasks_status_functional_from_ft_tests():
    html = '<html><body><section id="hero"><h1>x</h1></section></body></html>'
    ft = [
        {"n": "nav_links_validos", "p": 1, "d": ""},
        {"n": "botones_click_sin_error", "p": 1, "d": ""},
        {"n": "formularios_no_recargan", "p": 0, "d": "submit recarga"},
        {"n": "interactivos_responden", "p": 1, "d": ""},
        {"n": "js_sin_errores", "p": 1, "d": ""},
    ]
    st = subtasks_status(html, "", "", PORTFOLIO_TASK, ft)
    assert st["funcional:formularios_no_recargan"]["ok"] is False
    assert "recarga" in st["funcional:formularios_no_recargan"]["detail"]
    assert st["funcional:js_sin_errores"]["ok"] is True


def test_format_subtasks_status_shows_fail_with_detail():
    html = '<html><body><section id="hero"><h1>x</h1></section></body></html>'
    out = format_subtasks_status(html, "", "", PORTFOLIO_TASK, None)
    assert "CHECKLIST DE SUBTAREAS" in out
    assert "[FAIL] seccion:faq" in out
    assert "SUBTAREAS:" in out


# ---------- B3: novelty_score (explorar→explotar) ----------

def _cand(ref: dict, name: str) -> Path:
    return _write(ref, name)


def test_novelty_identical_is_zero():
    c = {"index.html": '<html><body><section id="a" class="x"><h1>H</h1></section></body></html>',
         "styles.css": "body{color:#111;background:#fff}",
         "app.js": "document.querySelector('#a');"}
    a = _cand(c, "novel_id")
    b = _cand(c, "novel_id2")
    assert novelty_score(a, b) == 0


def test_novelty_layout_change_is_high():
    base = {"index.html": '<html><body><header class="navbar"><nav><a id="h1">A</a></nav></header><main><section id="hero" class="grid-2"><h1>H</h1></section></main></body></html>',
            "styles.css": "body{color:#111;background:#fff}.grid-2{display:grid;grid-template-columns:1fr 1fr}",
            "app.js": "document.querySelector('#hero');"}
    alt = {"index.html": '<html><body><div class="masonry"><article id="card-a" class="tile"><h2>T</h2></article><article id="card-b" class="tile"><h2>U</h2></article></div></body></html>',
           "styles.css": "body{color:#ffd700;background:#0d0d0d}.masonry{display:grid;grid-template-areas:'a b' 'c d';gap:2rem}.tile{transform:rotate(-1deg) scale(1.02)}",
           "app.js": "document.querySelectorAll('.tile');"}
    a = _cand(base, "novel_base")
    b = _cand(alt, "novel_alt")
    assert novelty_score(a, b) >= 50


def test_novelty_just_faq_id_edit_is_low():
    base = {"index.html": '<html><body><section id="faq-1" aria-expanded="false"><h3>Q</h3></section></body></html>',
            "styles.css": "body{color:#222}",
            "app.js": ""}
    alt = {"index.html": '<html><body><section id="faq-2" aria-expanded="false"><h3>Q</h3></section></body></html>',
           "styles.css": "body{color:#222}",
           "app.js": ""}
    a = _cand(base, "novel_faq_a")
    b = _cand(alt, "novel_faq_b")
    assert novelty_score(a, b) < 20


def test_novelty_missing_reference_files():
    base = {"index.html": '<html><body><section><h1>H</h1></section></body></html>'}
    alt = {"index.html": '<html><body><div><h2>X</h2></div></body></html>',
           "styles.css": "body{color:#f00}", "app.js": "var x=1;"}
    a = _cand(base, "novel_miss_a")
    b = _cand(alt, "novel_miss_b")
    assert 0 <= novelty_score(a, b) <= 100


# ---------- A2: modo exploración en GenerateCandidate ----------

class _FakeLLM:
    def __init__(self, text):
        self._text = text

    def generate(self, prompt, temperature=0.7):
        self.prompt = prompt
        from types import SimpleNamespace
        return SimpleNamespace(text=self._text)


class _FakeEval:
    """Reemplaza evaluate() para que el test no dependa del evaluador real."""
    def __init__(self):
        self.calls = []

    def __call__(self, target, requirements=None, structure=None):
        self.calls.append(str(target))
        return {"total": 80, "seo": 80, "a11y": 80, "performance": 80,
                "responsive": 80, "best_practices": 80, "visual": 80,
                "task": 80, "structure": 80, "functional": 80}


def _fake_generate(text: str) -> GenerateCandidate:
    from tools.domain import web_generator as wg
    from pathlib import Path
    # workspace de prueba aislado (restaurar PATHS global tras el test)
    _orig_current = wg.PATHS.get("current")
    work = Path("/tmp/opencode") / "a2_ws"
    if work.exists():
        import shutil
        shutil.rmtree(work)
    work.mkdir(parents=True)
    wg.PATHS["current"] = work
    (work / "index.html").write_text("<html><body>SEED</body></html>")
    (work / "styles.css").write_text("body{color:#111}")
    (work / "app.js").write_text("var seed=1;")
    # asset huérfano del arquetipo anterior (debe desaparecer en modo exploración)
    (work / "graph_data.json").write_text("{'nodes':[]}")
    (work / "dump.js").write_text("console.log(1)")
    g = GenerateCandidate(llm=_FakeLLM(text), task=PORTFOLIO_TASK, archetype="portfolio")
    g._orig_current = _orig_current
    return g, work


def _restore(g):
    from tools.domain import web_generator as wg
    if g._orig_current is not None:
        wg.PATHS["current"] = g._orig_current


def test_explore_mode_cleans_target_and_does_not_inject_current_code():
    from unittest.mock import patch
    from tools.domain import web_generator as wg
    import tools.domain.evaluator as ev_mod
    g, work = _fake_generate("```html\nindex.html\n<!DOCTYPE html><html lang='es'><body><section id='hero' class='masonry'><h1>NUEVO</h1></section></body></html>\n```\n```css\nstyles.css\nbody{color:#ffd700}\n```\n```js\napp.js\nvar nuevo=1;\n```")
    with patch.object(ev_mod, "evaluate", _FakeEval()):
        out = g.run(objective="explora una variación de diseño rompe el layout")
    _restore(g)
    # prompt del subagente: en modo exploración NO se inyecta el código actual
    prompt = g.llm.prompt
    assert "MODO EXPLORACIÓN" in prompt
    assert "SEED" not in prompt
    # asset huérfano eliminado, reemplazado por los nuevos archivos
    assert not (work / "graph_data.json").exists()
    assert not (work / "dump.js").exists()
    assert (work / "index.html").exists()
    assert "masonry" in (work / "index.html").read_text()
    assert "OK:" in out


def test_normal_mode_keeps_current_code_and_orphans():
    from unittest.mock import patch
    from tools.domain import web_generator as wg
    import tools.domain.evaluator as ev_mod
    g, work = _fake_generate("```html\nindex.html\n<!DOCTYPE html><html lang='es'><body><section id='hero'><h1>MEJORADO</h1></section></body></html>\n```\n```css\nstyles.css\nbody{color:#111}\n```")
    with patch.object(ev_mod, "evaluate", _FakeEval()):
        out = g.run(objective="mejora el contraste")
    _restore(g)
    prompt = g.llm.prompt
    # modo normal: se hereda current_code y NO se limpian assets
    assert "MODO EXPLORACIÓN" not in prompt
    assert "SEED" in prompt
    assert (work / "graph_data.json").exists()
    assert (work / "dump.js").exists()
    assert "MEJORADO" in (work / "index.html").read_text()


# ---------- Punto 3 (Kimi K.3): salida estructurada de métricas ----------

def test_metrics_block_roundtrip():
    from tools.domain.evaluator import metrics_block, parse_metrics_block
    blk = metrics_block({"total": 90, "seo": 100, "visual": 46, "functional": 90})
    d = parse_metrics_block("texto antes\n" + blk + "\ntexto después")
    assert d == {"total": 90, "seo": 100, "visual": 46, "functional": 90}


def test_parse_metrics_block_missing_or_corrupt():
    from tools.domain.evaluator import parse_metrics_block
    assert parse_metrics_block("total=90 seo=100") is None
    assert parse_metrics_block("###METRICS###\n{rot\n###END_METRICS###") is None
    assert parse_metrics_block("###METRICS###\n[1,2,3]\n###END_METRICS###") is None


def test_metrics_block_appended_to_generate_candidate_output():
    from unittest.mock import patch
    from tools.domain import web_generator as wg
    import tools.domain.evaluator as ev_mod
    from tools.domain.evaluator import parse_metrics_block
    g, work = _fake_generate("```html\nindex.html\n<!DOCTYPE html><html lang='es'><body><section id='hero'><h1>X</h1></section></body></html>\n```\n```css\nstyles.css\nbody{}\n```")
    fake = _FakeEval()
    with patch.object(ev_mod, "evaluate", fake):
        out = g.run(objective="mejora el contraste")
    _restore(g)
    blk = parse_metrics_block(out)
    assert blk is not None and blk.get("total") == 80
    assert blk.get("visual") == 80
