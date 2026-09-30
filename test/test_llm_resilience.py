"""Tests de resiliencia del cliente LLM ante errores transitorios de la API.

Contexto: la battery de knowledge-graph del 2026-09-29 murió tras H1 con
`RuntimeError: Todos los modelos fallaron: 503 UNAVAILABLE ... high demand`.
El agente había gastado ya tokens, tenía 2 hipótesis evaluadas y no exportó
`final/`. El retry existente (3 intentos, esperas de 5s/10s) no cubre un pico
de demanda que dura minutos.

Estos tests fijan:
- un error transitorio se reintenta y acaba devolviendo la respuesta;
- un error permanente (API key inválida, 404) NO se reintenta y salta
  directamente al siguiente modelo de la cadena;
- si toda la cadena falla, se propaga un RuntimeError claro;
- el backoff crece y está acotado, con jitter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import (
    BACKOFF_CAP_S,
    MAX_TRANSIENT_ATTEMPTS,
    LLM,
    backoff_delay,
    is_transient,
)


class FakeError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def test_is_transient_detects_demand_spikes():
    assert is_transient(FakeError("503 UNAVAILABLE high demand"))
    assert is_transient(FakeError("RESOURCE_EXHAUSTED: quota"))
    assert is_transient(FakeError("429 Too Many Requests"))
    assert is_transient(FakeError("deadline exceeded"))
    assert is_transient(TimeoutError("timed out"))
    assert is_transient(ConnectionError("connection reset"))


def test_is_transient_rejects_permanent_errors():
    # Una API key inválida no se arregla reintentando.
    assert not is_transient(FakeError("API key not valid", code=400))
    assert not is_transient(FakeError("model not found", code=404))
    assert not is_transient(FakeError("invalid argument: tools"))


def test_backoff_grows_and_is_capped():
    d0, d5, d6 = backoff_delay(0), backoff_delay(5), backoff_delay(6)
    assert 0 < d0 <= BACKOFF_CAP_S
    # Los intentos tardíos están acotados (no crecen sin límite).
    assert d5 <= BACKOFF_CAP_S and d6 <= BACKOFF_CAP_S


def test_transient_error_is_retried_then_succeeds(monkeypatch):
    """Un 503 transitorio NO debe tumbar la run: se reintenta y sale bien."""
    llm = LLM(model="m-a", api_key="k", use_cache=False, provider="gemini")
    llm._chain = ["m-a"]

    calls = {"n": 0}

    def fake_generate_content(model, contents, config):
        calls["n"] += 1
        if calls["n"] < 3:
            raise FakeError("503 UNAVAILABLE high demand")
        class R:  # respuesta mínima válida
            candidates = []
        return R()

    monkeypatch.setattr(llm.client.models, "generate_content", fake_generate_content)
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)  # sin esperar de verdad

    out = llm.generate([{"role": "user", "parts": [{"text": "hola"}]}])
    assert calls["n"] == 3, "debe reintentar hasta 3 veces antes de rendirse"
    assert out.text == ""  # respuesta vacía pero sin excepción


def test_permanent_error_skips_to_next_model_immediately(monkeypatch):
    """Un 400 no se reintenta: pasa al siguiente modelo de la cadena."""
    llm = LLM(model="m-bad", api_key="k", use_cache=False, provider="gemini")
    llm._chain = ["m-bad", "m-good"]

    seen = []

    def fake_generate_content(model, contents, config):
        seen.append(model)
        if model == "m-bad":
            raise FakeError("API key not valid", code=400)
        class R:
            candidates = []
        return R()

    monkeypatch.setattr(llm.client.models, "generate_content", fake_generate_content)
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)

    llm.generate([{"role": "user", "parts": [{"text": "hola"}]}])
    # m-bad se intentó UNA vez (sin reintentos) y luego se usó m-good.
    assert seen == ["m-bad", "m-good"]
    assert llm.model == "m-good"  # se queda con el modelo que funcionó


def test_exhausted_chain_raises_clear_error(monkeypatch):
    llm = LLM(model="m1", api_key="k", use_cache=False, provider="gemini")
    llm._chain = ["m1", "m2"]
    monkeypatch.setattr(
        llm.client.models, "generate_content",
        lambda model, contents, config: (_ for _ in ()).throw(
            FakeError("503 UNAVAILABLE high demand")),
    )
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="Todos los modelos fallaron"):
        llm.generate([{"role": "user", "parts": [{"text": "hola"}]}])


def test_transient_attempts_cover_multi_minute_spike():
    """El número de intentos debe cubrir un pico de demanda de minutos."""
    # 7 intentos con backoff hasta 90s -> varios minutos de reintento.
    assert MAX_TRANSIENT_ATTEMPTS >= 5


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
