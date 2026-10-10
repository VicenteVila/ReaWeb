"""Tests de robustez del driver A/B ante cuotas agotadas.

Cubre las dos mejoras que permiten completar una batería cuando el proveedor
agota la cuota a mitad:
1. `LLM_SINGLE_MODEL`: colapsa la cadena de fallback al modelo base, para que el
   dataset no se contamine con modelos MEZCLADOS (flag->modelo distinto) y la
   batería pueda pausarse/resumirse entre días manteniendo `valid=True`.
2. Pausa limpia: reconocer errores de cuota ("429/quota/rate/413") para NO girar
   sobre un muro muerto y dejar un summary resumible (exit 3).
Todo local, 0 llamadas LLM.
"""
import json

import pytest

import config
import scripts.run_ab_pg_battery as battery
from scripts.run_ab_pg_battery import _is_quota_error, _write_summary


@pytest.fixture
def patched_config_model(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-3-flash-preview")
    monkeypatch.setattr(config, "LLM_SINGLE_MODEL", False)
    return config


# --- 1. clasificación de errores de cuota ---------------------------------

def test_quota_classifier_recognizes_quota_signals():
    assert _is_quota_error("429 RESOURCE_EXHAUSTED. quota exceeded limit: 0")
    assert _is_quota_error("ClientError: 429")
    assert _is_quota_error("reached your rate limit (ratelimit) for tokens per minute")
    assert _is_quota_error("413 Payload too large: itpm exceeded")
    assert not _is_quota_error("400 Bad Request: prompt too long for model context")
    assert not _is_quota_error("ConnectionError: timeout")


def test_write_summary_marks_paused_and_valid(monkeypatch, tmp_path):
    monkeypatch.setattr(battery, "OUT", tmp_path)
    res = [
        {"arch": "a", "task": "t", "cond": "on", "rep": 1, "best": 87,
         "provider": "groq", "model": "openai/gpt-oss-120b"},
        {"arch": "a", "task": "t", "cond": "off", "rep": 1, "best": 81,
         "provider": "groq", "model": "openai/gpt-oss-120b"},
    ]
    _write_summary(res, paused=True, note="cuota agotada")
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["valid"] is False and s["paused"] is True
    assert s["resolved_models"] == [["groq", "openai/gpt-oss-120b"]]
    assert s["failed_runs"] == []

    _write_summary(res)
    s2 = json.loads((tmp_path / "summary.json").read_text())
    assert s2["valid"] is True and s2["paused"] is False


def test_write_summary_flags_mixed_models(monkeypatch, tmp_path):
    monkeypatch.setattr(battery, "OUT", tmp_path)
    res = [
        {"arch": "a", "task": "t", "cond": "on", "rep": 1, "best": 87,
         "provider": "gemini", "model": "gemini-3-flash-preview"},
        {"arch": "a", "task": "t", "cond": "off", "rep": 1, "best": 81,
         "provider": "gemini", "model": "gemini-3.1-flash-lite"},
    ]
    _write_summary(res)
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["valid"] is False
    assert len(s["resolved_models"]) == 2


# --- LLM_SINGLE_MODEL: cadena sin fallback (integridad) -------------------

def _build_llm_single_model(provider, api_key):
    from agent.llm import LLM
    return LLM(model=None, provider=provider, api_key=api_key, use_cache=False)


def test_single_model_collapses_openai_compat_chain(monkeypatch, patched_config_model):
    monkeypatch.setattr(config, "LLM_SINGLE_MODEL", True)
    llm = _build_llm_single_model("groq", api_key="fake-key")
    assert llm._chain == ["openai/gpt-oss-120b"]
    assert llm.model == "openai/gpt-oss-120b"
    # el crítico VLM mantiene su modelo propio (no se ve afectado)
    assert llm._vision_models == ["qwen/qwen3.8-27b"]


def test_single_model_collapses_gemini_chain(monkeypatch, patched_config_model):
    monkeypatch.setattr(config, "LLM_SINGLE_MODEL", True)
    llm = _build_llm_single_model("gemini", api_key="fake-key")
    assert llm._chain == ["gemini-3-flash-preview"]
    assert llm.model == "gemini-3-flash-preview"
    assert llm._vision_models == ["gemini-3-flash-preview"]


def test_fallback_chain_intact_without_single_model(monkeypatch, patched_config_model):
    llm = _build_llm_single_model("groq", api_key="fake-key")
    assert "qwen/qwen3.8-27b" in llm._chain, "sin modo integridad hay fallback"
    assert len(llm._chain) == 2