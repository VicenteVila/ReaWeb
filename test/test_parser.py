"""Tests del parser de salida del subagente en GenerateCandidate (web_generator)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.domain.web_generator import GenerateCandidate


def test_parse_named_blocks():
    """Formato canónico: ===FILE=== seguido de nombre y contenido."""
    text = (
        "Preamble\n"
        "===FILE===\nindex.html\n<!DOCTYPE html><html></html>\n"
        "===FILE===\nstyles.css\nbody{color:red}\n"
        "===FILE===\napp.js\nconsole.log('x');\n"
    )
    files, fallback = GenerateCandidate._parse_files(text)
    assert "index.html" in files and files["index.html"].startswith("<!DOCTYPE")
    assert "styles.css" in files
    assert "app.js" in files
    assert not fallback


def test_parse_html_pegged_after_file_marker():
    """El fallo real: el subagente pegó el HTML directamente tras ===FILE===,
    sin la línea del nombre. Debe inferir index.html por contenido."""
    text = (
        "===FILE===\n"
        "<!DOCTYPE html>\n<html lang='es'><head><title>X</title></head>"
        "<body></body></html>\n"
        "===FILE===\nstyles.css\nbody{color:blue}\n"
        "===FILE===\napp.js\nconst svg=document.getElementById('graph');\n"
    )
    files, fallback = GenerateCandidate._parse_files(text)
    assert files.get("index.html", "").startswith("<!DOCTYPE")
    assert "styles.css" in files
    assert "app.js" in files
    assert fallback


def test_parse_markdown_fences():
    text = (
        "```html index.html\n<!DOCTYPE html><html></html>\n```\n"
        "```css styles.css\nbody{}\n```\n"
        "```js app.js\nconst x=1;\n```\n"
    )
    files, fallback = GenerateCandidate._parse_files(text)
    assert "index.html" in files
    assert "styles.css" in files
    assert "app.js" in files


def test_parse_fallback_guesses_by_content():
    """Sin delimitadores: fallback infiere index.html por <!DOCTYPE html>."""
    text = "<!DOCTYPE html>\n<html><body><h1>H</h1></body></html>"
    files, fallback = GenerateCandidate._parse_files(text)
    assert files.get("index.html", "").startswith("<!DOCTYPE")
    assert fallback


def test_parse_rejects_unsafe_names():
    text = "===FILE===\n../evil.html\nx\n"
    files, fallback = GenerateCandidate._parse_files(text)
    assert "index.html" not in files
    assert not any("/" in n for n in files)