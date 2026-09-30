"""Tests de la scoring v2: transporte HTTP, gate funcional P0 y versionado.

Contexto del bug que motivation esta versión (2026-09-29): el harness medía los
candidatos con `file://`, donde el origen es `null` y CORS bloquea cualquier
`fetch()` a un recurso local. El JS que dibuja el grafo nunca corría, el SVG
quedaba vacío, el test `grafo_visible` ni siquiera se registraba (buscaba un id
que la página no usaba) y la página rota pasaba el gate funcional con un 60 de
media. Resultado: el agente optimizaba un total que subía (76->83) mientras la
web no funcionaba.

Estos tests fijan el comportamiento correcto para que no vuelva:
- el render/test sirven por HTTP (el fetch funciona y el grafo se dibuja);
- un SVG declarado pero vacío es un fallo visible, no un silencio;
- un fallo P0 capa el score aunque la media sea alta;
- el historial de Task-CoEvolve no mezcla escalas de scoring distintas.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import FUNCTIONAL_P0_GATE, SCORING_VERSION
from tools.domain.evaluator import FUNCTIONAL_GATE_MIN, _p0_test_name
from tools.domain.functional_tester import (
    FUNCTIONAL_TESTS,
    missing_required_tests,
    run_functional_test,
)
from tools.domain.render_server import page_url, serve_dir

CHROME = None
try:
    from tools.domain.visual_critic import find_chrome
    CHROME = find_chrome()
except Exception:
    CHROME = None


# --- Transporte HTTP (Fase 1) ---

def test_serve_dir_serves_over_http():
    with serve_dir(Path(__file__).parent) as (base, server):
        assert server is not None
        assert base is not None
        assert base.startswith("http://")
        assert ":80" not in base  # puerto alto, no 80


def test_page_url_prefers_http_and_returns_stop_callable(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>x</body></html>")
    url, extra, stop = page_url(tmp_path / "index.html", project_dir=tmp_path)
    try:
        assert url.startswith("http://")
        assert url.endswith("/index.html")
        # En modo HTTP no debe aplicarse el flag de file://.
        assert "--allow-file-access-from-files" not in extra
    finally:
        stop()


def test_page_url_stop_terminates_server(tmp_path):
    """El servidor debe seguir vivo hasta que el llamador llame a stop().

    Regresión: si page_url devuelve la URL pero cierra el servidor antes de que
    Chrome la pida, Chrome recibe una página de error y el funcional sale None.
    """
    import urllib.request

    (tmp_path / "index.html").write_text("<html><body>hola</body></html>")
    url, _extra, stop = page_url(tmp_path / "index.html", project_dir=tmp_path)
    try:
        body = urllib.request.urlopen(url, timeout=5).read()
        assert b"hola" in body
    finally:
        stop()


# --- Detección del grafo y no-ops (Fase 2) ---

def test_missing_required_tests_flags_absent_obligatory():
    absent = missing_required_tests([{"n": "nav_links_validos", "p": 1}])
    assert "js_sin_errores" in absent
    assert "nav_links_validos" not in absent


def test_missing_required_tests_empty_when_all_ran():
    required = [n for n, req in FUNCTIONAL_TESTS if req]
    ran = [{"n": n, "p": 1} for n in required]
    # Todos los obligatorios ejecutados -> no falta ninguno. grafo_visible es
    # opcional y puede faltar sin penalizar.
    assert missing_required_tests(ran) == []
    assert "grafo_visible" not in required


def test_p0_gate_names():
    assert "grafo_visible" in FUNCTIONAL_P0_GATE
    assert "js_sin_errores" in FUNCTIONAL_P0_GATE
    assert "interactivos_responden" in FUNCTIONAL_P0_GATE
    # El gate agregado subió respecto al 60 original (la página rota sacaba 60).
    assert FUNCTIONAL_GATE_MIN >= 80


def test_p0_test_name_detects_p0_failures():
    assert _p0_test_name("[grafo_visible] SVG vacío") == "grafo_visible"
    assert _p0_test_name("[js_sin_errores] ReferenceError") == "js_sin_errores"
    # Un fallo no-P0 no activa el gate por test.
    assert _p0_test_name("[nav_links_validos] roto") is None
    assert _p0_test_name("texto suelto") is None


def test_manifest_declares_grafo_visible():
    names = [n for n, _ in FUNCTIONAL_TESTS]
    assert "grafo_visible" in names
    grafo_required = dict(FUNCTIONAL_TESTS)["grafo_visible"]
    # Es opcional: en páginas sin SVG no aplica y no debe penalizar.
    assert grafo_required is False


# --- Tests de integración con Chrome (se saltan si no hay Chrome) ---

def _write_graph_page(base: Path, with_data: bool):
    base.mkdir(parents=True, exist_ok=True)
    if with_data:
        (base / "data.json").write_text('{"repos":["a","b","c","d"]}')
    (base / "index.html").write_text(
        "<!DOCTYPE html><html><body>"
        "<section id='graph' class='graph-container'>"
        "<svg id='main-svg' width='800' height='600'></svg></section>"
        "<script>fetch('data.json').then(r=>r.json()).then(d=>{"
        "const s=document.getElementById('main-svg');"
        "d.repos.forEach((n,i)=>{const c=document.createElementNS("
        "'http://www.w3.org/2000/svg','circle');"
        "c.setAttribute('cx',100+i*50);c.setAttribute('cy',100);"
        "c.setAttribute('r',20);s.appendChild(c);});"
        "}).catch(()=>{});</script></body></html>"
    )
    return base / "index.html"


def test_functional_fetch_ok_graph_passes(tmp_path):
    if CHROME is None:
        return  # sin Chrome: el gate funcional no penaliza
    page = _write_graph_page(tmp_path / "ok", with_data=True)
    res = run_functional_test(page, timeout=90)
    assert res["ok"], res
    grafo = [t for t in res["tests"] if t["n"] == "grafo_visible"]
    assert grafo, "grafo_visible debe reportarse cuando hay SVG"
    assert grafo[0]["p"] == 1, grafo[0]["d"]


def test_functional_fetch_broken_graph_fails_and_caps(tmp_path):
    if CHROME is None:
        return
    page = _write_graph_page(tmp_path / "broken", with_data=False)  # sin data.json
    res = run_functional_test(page, timeout=90)
    assert res["ok"], res
    grafo = [t for t in res["tests"] if t["n"] == "grafo_visible"]
    assert grafo, "un SVG declarado pero vacío debe registrarse como fallo, no omitirse"
    assert grafo[0]["p"] == 0
    # El fallo P0 capa el score por debajo del 60 aunque el resto pase.
    assert res["functional"] < 60, res["functional"]


# --- Versionado del historial (Fase 3) ---

def test_scoring_version_is_two():
    assert SCORING_VERSION == 2


def test_load_history_filters_by_scoring_version(tmp_path):
    """El historial pre-v2 (NULL) no debe mezclarse con los de v2."""
    from agent.memory_db import MemoryDB
    from tools.domain.task_coevolve import load_history

    db = MemoryDB(path=tmp_path / "mem.db")
    # Fila nueva: se etiqueta con la versión vigente por defecto.
    db.add_task_eval(run_id="r1", task_id="a", task_hash="hash-v2",
                     archetype="landing-page", task="A", score=90.0)
    # Fila legacy: insertada con scoring_version NULL explícito.
    db.conn.execute(
        "INSERT INTO task_evals (run_id, task_id, task_hash, archetype, task, "
        "score, scoring_version, ts) VALUES (?,?,?,?,?,?,?,?)",
        ("r0", "a", "hash-legacy", "landing-page", "A", 40.0, None, "2020-01-01"),
    )
    db.conn.commit()

    hist = load_history(db, scoring_version=SCORING_VERSION)
    assert "hash-v2" in hist
    assert "hash-legacy" not in hist, "el historial legacy no debe contaminar v2"
    assert hist["hash-v2"] == [0.9]


def test_add_task_eval_defaults_to_current_version(tmp_path):
    from agent.memory_db import MemoryDB

    db = MemoryDB(path=tmp_path / "mem.db")
    db.add_task_eval(run_id="r1", task_id="a", task_hash="h",
                     archetype="landing-page", task="A", score=75.0)
    row = db.task_evals(task_hash="h")[0]
    assert row["scoring_version"] == SCORING_VERSION


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
