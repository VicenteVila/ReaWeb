"""Tests del crítico VLM (capa estética de AutoDesign): parseo, fallback sin
Chrome y registro del axis vlm en el árbol del agente."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.domain.visual_critic import AuditVisual, find_chrome, render_screenshot
from tools.domain.evaluator import blend_visual_total


def test_blend_visual_total_uses_max_when_vlm_higher():
    m = {"total": 79, "seo": 75, "a11y": 80, "performance": 80,
         "responsive": 100, "best_practices": 80, "visual": 46,
         "task": 91, "structure": 100, "gates": {}}
    assert blend_visual_total(m, 65) == 83
    assert blend_visual_total(m, 75) == 85
    assert blend_visual_total(m, None) == 79


def test_blend_visual_total_keeps_blocking_gate():
    m = {"total": 79, "seo": 75, "a11y": 80, "performance": 80,
         "responsive": 100, "best_practices": 80, "visual": 46,
         "task": 91, "structure": 100, "gates": {"structure": ["topics"]}}
    assert blend_visual_total(m, 90) == 40


def test_blend_visual_total_requires_total():
    assert blend_visual_total({"visual": 50}, 60) is None


def test_parse_clean_json():
    raw = '{"score": 85, "issues": ["A", "B"], "suggestions": ["S1", "S2"]}'
    score, issues, sugg = AuditVisual._parse(raw)
    assert score == 85
    assert issues == ["A", "B"]
    assert sugg == ["S1", "S2"]


def test_parse_with_markdown_fence():
    raw = "```json\n{\"score\": 40, \"issues\": [], \"suggestions\": [\"más contraste\"]}\n```"
    score, issues, sugg = AuditVisual._parse(raw)
    assert score == 40
    assert sugg == ["más contraste"]


def test_parse_tolerates_noise():
    raw = "Analicé la imagen.\n{ \"score\": 72, \"issues\": [\"descentrado\"], \"suggestions\": [\"\"] }\nfin"
    score, issues, sugg = AuditVisual._parse(raw)
    assert score == 72
    assert issues == ["descentrado"]
    assert sugg == []


def test_parse_clamps_score_and_limits():
    raw = '{"score": 150, "issues": ["1","2","3","4","5"], "suggestions": ["a","b","c","d","e","f"]}'
    score, issues, sugg = AuditVisual._parse(raw)
    assert score == 100
    assert len(issues) == 4
    assert len(sugg) == 4


def test_parse_empty_and_invalid():
    assert AuditVisual._parse("") == (0, [], [])
    assert AuditVisual._parse("no json here") == (0, [], [])
    assert AuditVisual._parse("{\"score\": \"nope\"}") == (0, [], [])


def test_find_chrome_or_none():
    # debe devolver una ruta existente o None, sin romper
    c = find_chrome()
    assert c is None or Path(c).exists()


def test_render_screenshot_without_chrome_returns_false(tmp_path):
    # Si no hay Chrome, devuelve False (el fallback maneja el caso)
    html = tmp_path / "index.html"
    html.write_text("<!DOCTYPE html><html><body>x</body></html>")
    png = tmp_path / "out.png"
    if find_chrome() is None:
        assert render_screenshot(html, png) is False
    else:
        # con Chrome disponible, puede renderizar; aceptamos True o False sin assert duro
        ok = render_screenshot(html, png)
        assert isinstance(ok, bool)


def test_audit_visual_returns_error_without_html(tmp_path, monkeypatch):
    from agent.agent import Agent
    from config import PATHS

    run_dir = tmp_path / "runs" / "vlm-nohtml"
    run_dir.mkdir(parents=True, exist_ok=True)

    class _FakeLLM:
        model = "fake"
        def generate_vision(self, *a, **k):
            raise AssertionError("no debe llamarse sin index.html")

    agent = Agent(_FakeLLM(), archetype_name="landing-page", task="landing",
                  run_dir=run_dir, verbose=False, max_turns=2)
    agent.db = None
    agent.tree.db = None
    agent.tree.path = run_dir / "search_tree.json"
    agent.tree.nodes = {}

    # ocultar cualquier index.html en workspace
    wc = PATHS["current"]
    wc.mkdir(parents=True, exist_ok=True)
    had = (wc / "index.html").exists()
    if had:
        (wc / "index.html").rename(wc / "index.html.bak")

    try:
        tool = AuditVisual(llm=_FakeLLM())
        res = tool.run()
        assert "ERROR" in res
    finally:
        if had:
            (wc / "index.html.bak").rename(wc / "index.html")
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)


def test_handle_eval_result_registers_vlm_axis(tmp_path, monkeypatch):
    """El handler del agente añade el axis vlm al nodo y recombina el total."""
    from agent.agent import Agent
    from agent.state import TreeNode

    run_dir = tmp_path / "runs" / "vlm-axis"
    run_dir.mkdir(parents=True, exist_ok=True)

    class _FakeLLM:
        model = "fake"

    agent = Agent(_FakeLLM(), archetype_name="knowledge-graph", task="grafo",
                  run_dir=run_dir, verbose=False, max_turns=2)
    agent.db = None
    agent.tree.db = None
    agent.tree.path = run_dir / "search_tree.json"
    agent.tree.nodes = {}

    # seed: H0 como nodo actual con ejes completos (como devuelve evaluate())
    agent.tree.add(TreeNode(id="H0", parent=None, action="seed_workspace",
                            metrics={"total": 79, "seo": 75, "a11y": 80,
                                     "performance": 80, "responsive": 100,
                                     "best_practices": 80, "visual": 46,
                                     "task": 91, "structure": 100, "gates": {}},
                            status="best_branch"))
    agent.hypothesis_count = 1

    class _Call:
        name = "audit_visual"
        args = {}

    node = agent._handle_eval_result(_Call(), "visual_vlm=63 | issues: x\nsugerencias: y")
    assert node == "H0"
    assert agent.tree.nodes["H0"].metrics.get("vlm") == 63
    assert agent.tree.nodes["H0"].metrics.get("visual") == 63
    assert agent.tree.nodes["H0"].metrics.get("total") == 83
    assert agent.hypothesis_count == 1, "no debe crear hipótesis nueva"

    import shutil
    shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))