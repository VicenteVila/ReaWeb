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
        (d / fname).write_text(content)
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
    js = 'const c=document.getElementById("c").getContext("2d");function a(){c.fillRect(0,0,1,1);requestAnimationFrame(a)}a();'
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
    m = evaluate(d)  # sin requirements
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
    <body><main><section><h1>Único</h1></section></main>
    <canvas id="c"></canvas>
    <script>const io=new IntersectionObserver(()=>{});</script></body></html>"""
    css = """body{background:linear-gradient(90deg,#000,#333)}
    nav{position:sticky;top:0}
    @keyframes fade{from{opacity:0}to{opacity:1}}
    .card{transition:transform .2s}
    .card:hover{transform:scale(1.05);animation:fade 1s}
    @media (prefers-color-scheme:dark){body{background:#111}}
    @media (prefers-reduced-motion:reduce){*{animation:none}}
    """
    js = ('const c=document.getElementById("c").getContext("2d");'
          'function a(){c.fillRect(0,0,1,1);requestAnimationFrame(a)}a();'
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