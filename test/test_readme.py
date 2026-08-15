"""Tests de la tool fetch_readme (con urllib mockeado, sin tocar la red)."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tools.domain.readme_fetcher as rf
from config import PATHS

README_MAIN = "# TraceForge\n\nBuen repo **genial**\n\n```python\nprint(1)\n```"
README_MASTER = "# PromptForge\n\nSolo en master"
RENDERED = "<h1>TraceForge</h1><p>Buen repo <strong>genial</strong></p><script>alert(1)</script>"


def _mock_downloads(url: str, payload: dict | None = None):
    """Devuelve respuestas simuladas según la URL."""
    if url.endswith("/TraceForge/main/README.md"):
        return 200, README_MAIN
    if url.endswith("/PromptForge/main/README.md"):
        return 404, ""
    if url.endswith("/PromptForge/master/README.md"):
        return 200, README_MASTER
    if url == "https://api.github.com/markdown":
        # render reflectivo: saca el título del markdown enviado
        text = (payload or {}).get("text", "")
        m = re.match(r"#\s*(\w+)", text)
        title = m.group(1) if m else "X"
        return 200, f"<h1>{title}</h1><script>alert(1)</script>"
    return 404, ""


def test_parse_github_repos():
    from tools.domain.readme_fetcher import parse_github_repos
    assert parse_github_repos("github.com/VicenteVila/TraceForge y X") == ["TraceForge"]
    assert parse_github_repos("github.com/VicenteVila: TraceForge, CogniTeam") == ["CogniTeam", "TraceForge"]
    assert parse_github_repos("no hay repos") == []


def test_sanitize():
    s = rf._sanitize('<h1>X</h1><script>alert(1)</script><a onclick="e()" href="javascript:b()">l</a><iframe src="x"></iframe>')
    assert "<script" not in s
    assert "<iframe" not in s
    assert "onclick" not in s
    assert 'href="javascript' not in s
    assert "<h1>X</h1>" in s


def test_render_fallback():
    html = rf._render_fallback("# Titulo\n\n**negrita** y `code`\n\n```python\nprint(1)\n```")
    assert "<h1>Titulo</h1>" in html
    assert "<strong>negrita</strong>" in html
    assert "<pre><code" in html


def test_fetch_readme_ok(tmp_repos=True):
    PATHS["current"].mkdir(parents=True, exist_ok=True)
    (PATHS["current"] / "repos").mkdir(parents=True, exist_ok=True)

    tool = rf.FetchReadme(task="github.com/VicenteVila/TraceForge")
    with mock.patch.object(rf, "_http_get", side_effect=_mock_downloads), \
         mock.patch.object(rf, "_http_post_json", side_effect=_mock_downloads):
        result = tool.run(run_id="t-readme")
    assert "OK: páginas README generadas" in result
    assert "repos/TraceForge/index.html" in result
    page = (PATHS["current"] / "repos" / "TraceForge" / "index.html").read_text()
    assert "<title>TraceForge · README</title>" in page
    assert '<a class="back" href="../index.html">' in page
    assert "<script>alert" not in page  # sanitizado
    assert "TraceForge</h1>" in page or "<h1>TraceForge</h1>" in page

    import shutil
    shutil.rmtree(PATHS["current"] / "repos", ignore_errors=True)


def test_fetch_readme_fallback_branch():
    """PromptForge usa master: debe probar main (404) y caer a master."""
    PATHS["current"].mkdir(parents=True, exist_ok=True)
    tool = rf.FetchReadme(task="github.com/VicenteVila/PromptForge")
    with mock.patch.object(rf, "_http_get", side_effect=_mock_downloads), \
         mock.patch.object(rf, "_http_post_json", side_effect=_mock_downloads):
        result = tool.run(run_id="t-readme-master")
    assert "repos/PromptForge/index.html" in result
    page = (PATHS["current"] / "repos" / "PromptForge" / "index.html").read_text()
    assert "<h1>PromptForge</h1>" in page
    import shutil
    shutil.rmtree(PATHS["current"] / "repos", ignore_errors=True)


def test_fetch_readme_render_fallback_on_api_failure():
    """Si la API de render falla, usa el mini-convertidor local."""
    PATHS["current"].mkdir(parents=True, exist_ok=True)

    def _http_get_fail(url, timeout=15):
        if url.endswith("/TraceForge/main/README.md"):
            return 200, README_MAIN
        return 404, ""

    tool = rf.FetchReadme(task="github.com/VicenteVila/TraceForge")
    with mock.patch.object(rf, "_http_get", side_effect=_http_get_fail), \
         mock.patch.object(rf, "_http_post_json", return_value=(500, "")):
        result = tool.run(run_id="t-readme-fb")
    assert "repos/TraceForge/index.html" in result
    page = (PATHS["current"] / "repos" / "TraceForge" / "index.html").read_text()
    assert "<h1>TraceForge</h1>" in page
    import shutil
    shutil.rmtree(PATHS["current"] / "repos", ignore_errors=True)


def test_fetch_readme_no_repos():
    tool = rf.FetchReadme(task="no hay repos aqui")
    assert "ERROR" in tool.run()


if __name__ == "__main__":
    for fn in [test_parse_github_repos, test_sanitize, test_render_fallback,
               test_fetch_readme_ok, test_fetch_readme_fallback_branch,
               test_fetch_readme_render_fallback_on_api_failure, test_fetch_readme_no_repos]:
        fn()
        print(f"OK {fn.__name__}")
    print("Todos los tests de fetch_readme OK")