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
    d = _write({"index.html": GOOD_HTML, "styles.css": "body{}</style>", "app.js": ""}, "good")
    m = evaluate(d)
    assert m["total"] >= 80, m
    assert m["seo"] >= 70, m


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