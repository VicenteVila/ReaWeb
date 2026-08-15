"""Tests de la tool fetch_url (con servidor HTTP local) y del prompt con referencia."""
from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PATHS
from tools.domain.web_generator import FetchUrl, GENERATOR_PROMPT

HTML_FIXTURE = """<!DOCTYPE html><html><head><title>TestSite - Demo</title>
<meta name="description" content="Demo de prueba"><style>.x{color:red}</style></head>
<body><nav><a href="/pricing">Pricing</a><a href="/login">Login</a></nav>
<main><h1>Principal</h1><h2>Seccion A</h2><p>contenido de ejemplo</p></main>
<script>console.log('ignored')</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML_FIXTURE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_fetch_url_ok(tmp_path: Path | None = None):
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        import os
        os.environ.setdefault("GEMINI_API_KEY", "x")  # solo para imports
        ref_dir = PATHS["runs"] / "test-fetch"
        ref_dir.mkdir(parents=True, exist_ok=True)
        (PATHS["current"].parent).mkdir(parents=True, exist_ok=True)
        tool = FetchUrl()
        result = tool.run(url=f"http://127.0.0.1:{port}/", run_id="test-fetch")
        assert "OK: HTML descargado" in result
        assert "TITLE: TestSite - Demo" in result
        assert "H1: Principal" in result
        assert "NAV:" in result and "Pricing" in result
        assert "CONTENIDO:" in result
        assert "console.log" not in result  # scripts quitados del extracto
        # archivos guardados
        saved = list(ref_dir.rglob("*.html"))
        assert saved, "no se guardó reference/ en la run"
        assert (PATHS["current"].parent / "reference.html").exists()
        # limpieza
        import shutil
        shutil.rmtree(ref_dir, ignore_errors=True)
        (PATHS["current"].parent / "reference.html").unlink(missing_ok=True)
    finally:
        server.shutdown()
        t.join()


def test_fetch_url_invalid():
    tool = FetchUrl()
    assert "ERROR: URL inválida" in tool.run(url="no-es-url")
    assert "ERROR: URL inválida" in tool.run(url="ftp://x.com")


def test_generator_prompt_includes_reference():
    assert "REFERENCIA" in GENERATOR_PROMPT
    assert "{reference}" in GENERATOR_PROMPT


def test_run_config_has_initial_url():
    import json
    from .test_memory import __name__ as _  # noqa  (evita import cíclico)

if __name__ == "__main__":
    test_fetch_url_ok()
    print("OK test_fetch_url_ok")
    test_fetch_url_invalid()
    print("OK test_fetch_url_invalid")
    test_generator_prompt_includes_reference()
    print("OK test_generator_prompt_includes_reference")