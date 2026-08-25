"""Tests del pipeline de diseño (Punto 11): caché de visión, feedback
estructurado (fails/VLM) y forma YAML del meta-editor."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from agent.llm import LLM
from tools.domain.evaluator import metrics_block, parse_metrics_block
from tools.domain.meta_editor import EditSkill, _is_well_shaped


# --- F1: los críticos visuales no pasan por la caché ---

def test_generate_vision_signature_accepts_use_cache_false():
    """generate_vision expone use_cache; con False la caché no se consulta ni escribe."""
    llm = LLM.__new__(LLM)  # sin __init__: no requiere API key
    calls = {"get": 0, "put": 0}

    class FakeCache:
        def get(self, *a, **k):
            calls["get"] += 1
            return None

        def put(self, *a, **k):
            calls["put"] += 1

    llm.cache = FakeCache()
    llm.model = "fake"
    llm._chain = ["fake"]
    llm.last_usage = (0, 0)
    llm.cost_so_far = 0.0

    class FakeClient:
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                class U:
                    prompt_token_count = 10
                    candidates_token_count = 5
                class C:
                    usage_metadata = U()
                    candidates = []
                return C()

    llm.client = FakeClient()

    from google.genai import types as google_types
    config = google_types.GenerateContentConfig(temperature=0.3)
    part_text = google_types.Part.from_text(text="hola")
    part_img = google_types.Part.from_bytes(data=b"png", mime_type="image/png")
    llm._complete([part_text, part_img], config, kind="vision", use_cache=False)
    assert calls["get"] == 0 and calls["put"] == 0

    llm._complete([part_text, part_img], config, kind="vision", use_cache=True)
    assert calls["get"] == 1 and calls["put"] == 1


# --- F2: feedback estructurado en metrics_block ---

def test_metrics_block_carries_short_lists():
    mb = metrics_block({
        "total": 75,
        "fails": [f"fallo {i}" for i in range(10)],       # se recorta a 6
        "vlm_suggestions": ["mutación concreta"],
        "files": {"index.html": "x"},                      # dict => excluido
    })
    data = parse_metrics_block(mb)
    assert data["total"] == 75
    assert len(data["fails"]) == 6
    assert data["vlm_suggestions"] == ["mutación concreta"]
    assert "files" not in data


def test_metrics_block_truncates_long_items_and_skips_empty():
    mb = metrics_block({"fails": [], "visual": ["x" * 300]})
    data = parse_metrics_block(mb)
    assert "fails" not in data          # lista vacía no viaja
    assert len(data["visual"][0]) == 160


# --- F4: forma YAML estricta en el meta-editor ---

def test_well_shaped_accepts_declarative_yaml():
    good = yaml.safe_load("""
conversion_rules:
  - mobile_first
design_system:
  paleta:
    primario: "#4F46E5"
    acento: "#F59E0B"
""")
    assert _is_well_shaped(good)


def test_well_shaped_rejects_paragraph_contamination():
    """El caso real: prosa concatenada que parsea como clave-paragrapho."""
    bad = yaml.safe_load(
        "conversion_rules:\n  - mobile_first\n\n"
        "Añadir regla para portfolios interactivos: 1. Los filtros deben ser "
        "combinables (categoría + búsqueda). 2. El tema (dark/light) debe "
        "persistirse en localStorage entre sesiones del usuario.\n"
    )
    assert isinstance(bad, dict)
    assert not _is_well_shaped(bad)


def test_edit_skill_rejects_paragraph_append(tmp_path):
    from config import PATHS
    file = "generated/test-design-tmp.yaml"
    target = PATHS["domain"] / file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("reglas:\n  - una\n")
    tool = EditSkill()
    res = tool.run(
        component="context_memory",
        path=file,
        instruction="Añadir regla nueva: 1. Esto es un párrafo entero colgado de "
                    "una clave porque el agente pegó prosa en vez de YAML "
                    "estructurado; reproduce exactamente el patrón de la "
                    "contaminación real detectada en landing-page/rules.yaml.",
        mode="append",
        run_id="t-design-gate",
    )
    assert "ERROR" in res and "forma declarativa" in res
    # limpieza
    target.unlink(missing_ok=True)
    import sqlite3
    db = sqlite3.connect(PATHS["memory"] / "memory.db")
    db.execute("DELETE FROM harness_edits WHERE run_id='t-design-gate'")
    db.commit(); db.close()
    import shutil
    shutil.rmtree(PATHS["domain"] / ".proposals", ignore_errors=True)
