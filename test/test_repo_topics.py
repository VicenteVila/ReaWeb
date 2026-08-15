"""Tests de la tool fetch_repo_topics (con urllib y llm mockeados, sin tocar red/API)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PATHS  # noqa: E402
from tools.domain.repo_topics import FetchRepoTopics, CLASSIFY_PROMPT  # noqa: E402

README_MAIN = "# TraceForge\n\nAgentes autónomos con LLMs, multiagente, aprendizaje reforzado y visión."


class _FakeLLM:
    def __init__(self, text):
        self._text = text

    def generate(self, prompt, **kwargs):
        return type("R", (), {"text": self._text})


def _mock_http_get(url, timeout=15):
    if url.endswith("/TraceForge/main/README.md"):
        return 200, README_MAIN
    return 404, ""


def _fresh():
    PATHS["current"].mkdir(parents=True, exist_ok=True)
    gf = PATHS["current"] / "graph_data.json"
    if gf.exists():
        gf.unlink()
    return gf


def test_classify_prompt_has_subjects():
    assert "cs.AI" in CLASSIFY_PROMPT
    assert "{repo}" in CLASSIFY_PROMPT
    assert "{readme_snippet}" in CLASSIFY_PROMPT


def test_fetch_repo_topics_ok():
    gf = _fresh()
    llm = _FakeLLM(
        '{"topics": [{"code": "cs.AI", "desc": "Agentes autónomos"}, '
        '{"code": "cs.MA", "desc": "Multiagente"}, '
        '{"code": "cs.CV", "desc": "Visión"}]}'
    )
    tool = FetchRepoTopics(llm=llm, task="github.com/VicenteVila/TraceForge")
    with mock.patch("tools.domain.readme_fetcher._http_get", side_effect=_mock_http_get):
        result = tool.run(run_id="t-topics")
    assert "OK:" in result
    assert "TraceForge" in result
    assert "cs.AI" in result and "cs.MA" in result and "cs.CV" in result
    assert gf.exists()
    data = json.loads(gf.read_text())
    assert data["root"] == {"name": "Vicente Vila", "email": "vicentevilaramirez@gmail.com"}
    assert data["repos"][0]["name"] == "TraceForge"
    assert data["repos"][0]["topics"][0]["code"] == "cs.AI"
    gf.unlink()
    shutil.rmtree(PATHS["runs"] / "t-topics", ignore_errors=True)


def test_fetch_repo_topics_no_repos():
    tool = FetchRepoTopics(llm=_FakeLLM("{}"), task="sin repos")
    assert "ERROR" in tool.run()


def test_fetch_repo_topics_parses_noise():
    """El LLM devuelve texto con markdown alrededor: se extrae el JSON igualmente."""
    gf = _fresh()
    llm = _FakeLLM('```json\n{"topics": [{"code": "cs.LG", "desc": "Aprendizaje"}]}\n```')
    tool = FetchRepoTopics(llm=llm, task="github.com/VicenteVila/TraceForge")
    with mock.patch("tools.domain.readme_fetcher._http_get", side_effect=_mock_http_get):
        result = tool.run(run_id="t-topics-noise")
    assert "cs.LG" in result
    data = json.loads(gf.read_text())
    assert data["repos"][0]["topics"] == [{"code": "cs.LG", "desc": "Aprendizaje"}]
    gf.unlink()
    shutil.rmtree(PATHS["runs"] / "t-topics-noise", ignore_errors=True)


def test_fetch_repo_topics_filters_non_cs():
    """Las categorías que no empiezan por cs. se descartan."""
    gf = _fresh()
    llm = _FakeLLM('{"topics": [{"code": "physics.gen-ph", "desc": "No aplica"}]}')
    tool = FetchRepoTopics(llm=llm, task="github.com/VicenteVila/TraceForge")
    with mock.patch("tools.domain.readme_fetcher._http_get", side_effect=_mock_http_get):
        result = tool.run(run_id="t-topics-filter")
    assert "generado con 1 repos" in result
    data = json.loads(gf.read_text())
    assert data["repos"][0]["topics"] == []
    gf.unlink()
    shutil.rmtree(PATHS["runs"] / "t-topics-filter", ignore_errors=True)


if __name__ == "__main__":
    for fn in [test_classify_prompt_has_subjects, test_fetch_repo_topics_ok,
               test_fetch_repo_topics_no_repos, test_fetch_repo_topics_parses_noise,
               test_fetch_repo_topics_filters_non_cs]:
        fn()
        print(f"OK {fn.__name__}")
    print("Todos los tests de fetch_repo_topics OK")