"""Tests de la caché semántica de LLM (Punto 2, Qwen 3.8).

Cubre: put/get con hit por similitud, miss por umbral, indexación FAISS,
TTL, fallback de embedding local (sin API), y el hook en LLM._complete
sin tocar la red (embedding determinista inyectado).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from agent.llm import LLMCache, LLM
from config import PATHS


def _embed_identity(text: str) -> np.ndarray:
    """Embedding determinista sin red (trigramas hasheados -> bucket normalizado).
    Textos idénticos => cos=1.0; textos no relacionados => cos bajo."""
    return LLMCache._embed_local(text, dim=384)


@pytest.fixture()
def cache(tmp_path):
    return LLMCache(db_path=tmp_path / "cache.db", threshold=0.80,
                    ttl_days=7, embed_fn=_embed_identity)


def test_put_get_hit(cache):
    cache.put("genera una landing para SaaS", "m1", "text",
              response="<h1>SaaS</h1>", input_tokens=100, output_tokens=20)
    hit = cache.get("genera una landing para SaaS", "m1", "text")
    assert hit is not None
    assert hit["response"] == "<h1>SaaS</h1>"
    assert hit["input_tokens"] == 100
    assert cache.hits == 1
    assert cache.misses == 0


def test_similar_prompt_hits(cache):
    cache.put("genera una landing para SaaS de IA", "m1", "text",
              response="<h1>SaaS IA</h1>")
    # Misma petición con redacción ligeramente distinta => cos alto (0.80)
    hit = cache.get("genera una landing para SaaS de IA  ", "m1", "text")
    assert hit is not None, "prompts casi idénticos deben acertar con umbral 0.80"
    assert hit["similarity"] >= 0.80


def test_unrelated_prompt_misses(cache):
    cache.put("genera una landing para SaaS de IA", "m1", "text",
              response="<h1>SaaS</h1>")
    hit = cache.get("analiza este HTML y reporta fallos", "m1", "text")
    assert hit is None
    assert cache.misses == 1


def test_model_isolation(cache):
    cache.put("prompt comun", "model-a", "text", response="respuesta A")
    assert cache.get("prompt comun", "model-b", "text") is None
    assert cache.get("prompt comun", "model-a", "text") is not None


def test_kind_isolation(cache):
    cache.put("analiza esta pagina", "m1", "vision", response="score 90")
    assert cache.get("analiza esta pagina", "m1", "text") is None
    assert cache.get("analiza esta pagina", "m1", "vision") is not None


def test_faiss_index_built_and_rebuilt(cache):
    cache.put("primer prompt", "m1", "text", response="r1")
    cache.put("segundo prompt", "m1", "text", response="r2")
    assert cache.get("segundo prompt", "m1", "text") is not None
    # nuevo insert invalida el índice y se reconstruye con el nuevo vecino
    cache.put("tercer prompt", "m1", "text", response="r3")
    assert cache.get("tercer prompt", "m1", "text") is not None
    assert cache._index is not None


def test_ttl_expiry(tmp_path):
    import time as _time
    c = LLMCache(db_path=tmp_path / "ttl.db", threshold=0.80, ttl_days=1,
                 embed_fn=_embed_identity)
    c.put("prompt con ttl", "m1", "text", response="r")
    # backdateamos la entrada más allá del TTL (1 día)
    c._conn.execute(
        "UPDATE llm_cache SET created_ts=? WHERE prompt_hash=?",
        (_time.time() - 2 * 86400, LLMCache._prompt_hash("prompt con ttl")),
    )
    c._conn.commit()
    assert c.get("prompt con ttl", "m1", "text") is None


def test_embed_local_fallback_deterministic():
    a = LLMCache._embed_local("genera una landing para SaaS")
    b = LLMCache._embed_local("genera una landing para SaaS")
    assert np.allclose(a, b)
    norm = float(np.linalg.norm(a))
    assert norm > 0.99  # normalizado


def test_stats_and_close(cache):
    cache.put("p", "m1", "text", response="r")
    cache.get("p", "m1", "text")
    stats = cache.stats()
    assert stats["hits"] == 1
    cache.close()


class _FakeModels:
    def generate_content(self, *a, **k):
        raise AssertionError("generate_content no debe llamarse (la caché responde)")

class _FakeClient:
    def __init__(self, *a, **k):
        self.models = _FakeModels()


def test_llm_hook_uses_cache(monkeypatch, tmp_path):
    """LLM con caché: la segunda llamada idéntica devuelve la respuesta cacheada
    sin tocar la red (método _complete parcheado para que falle si se llama)."""
    import config as cfg
    monkeypatch.setattr(cfg, "LLM_CACHE_ENABLED", True)
    monkeypatch.setattr("agent.llm.LLMCache", LLMCache)
    monkeypatch.setattr("agent.llm.genai.Client", _FakeClient)

    llm = LLM(model="m1", api_key="fake-key", use_cache=True)
    llm.cache = LLMCache(db_path=tmp_path / "hook.db", threshold=0.80,
                         embed_fn=_embed_identity)

    called = {"n": 0}

    def fake_complete(*a, **k):
        called["n"] += 1
        part = type("P", (), {"text": "respuesta real", "function_call": None})()
        content = type("C", (), {"parts": [part]})()
        cand = type("Cand", (), {"content": content})()
        resp = type("R", (), {"candidates": [cand], "usage_metadata": None})()
        return resp

    llm.client.models.generate_content = fake_complete
    # forzamos el camino: _complete consulta caché y en miss llama a generate_content
    first = llm._complete("hola mundo", type("C", (), {"tools": None, "temperature": 0.7})())
    second = llm._complete("hola mundo", type("C", (), {"tools": None, "temperature": 0.7})())
    assert called["n"] == 1, "la segunda llamada debe venir de caché"
    assert first.text == second.text == "respuesta real"
    assert llm.cache.stats()["hits"] == 1
