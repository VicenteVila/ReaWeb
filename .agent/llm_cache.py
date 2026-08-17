"""Caché semántica de respuestas LLM (Punto 2, Qwen 3.8).

Evita pagar por llamadas repetidas a Gemini cuando una run se re-ejecuta para
validar un cambio del harness: prompts de la misma tarea (mismo task_hash, mismo
estado) generan respuestas casi idénticas. La caché busca por SIMILITUD DE
COSENO del embedding (no por hash exacto) y devuelve la respuesta previa si el
mejor vecino supera un umbral configurable.

Diseño:
  - tabla `llm_cache` en memory/memory.db (misma DB SQLite del harness)
  - embeddings vía `client.models.embed_content` (Gemini); fallback determinista
    a hash-local si el servicio no está disponible (la caché NUNCA rompe la run)
  - índice FAISS (IndexFlatIP) en memoria para búsqueda rápida de vecinos
  - umbral configurable LLM_CACHE_THRESHOLD (default 0.80)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone

from config import LLM_CACHE_THRESHOLD, LLM_CACHE_TTL_DAYS, PATHS

_NP = None


def _np():
    """Import perezoso de numpy (solo al usarlo). Evita que la caché rompa la
    colección de tests en entornos sin numpy instalado."""
    global _NP
    if _NP is None:
        import numpy as _m
        _NP = _m
    return _NP


class LLMCache:
    def __init__(self, db_path=None, threshold: float | None = None,
                 ttl_days: int | None = None, embed_fn=None):
        self.path = db_path or (PATHS["memory"] / "memory.db")
        self.threshold = threshold if threshold is not None else LLM_CACHE_THRESHOLD
        self.ttl_days = ttl_days if ttl_days is not None else LLM_CACHE_TTL_DAYS
        self._embed_fn = embed_fn  # override para tests
        self.hits = 0
        self.misses = 0
        self.cost_saved_usd = 0.0
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()
        # índice FAISS: se construye perezosamente a partir de la DB
        self._index = None
        self._index_ids: list[int] = []
        self._index_model = None

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_cache (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                prompt_hash TEXT NOT NULL,
                model       TEXT NOT NULL,
                kind        TEXT NOT NULL DEFAULT 'text',
                embedding   BLOB,
                response    TEXT,
                tool_calls  TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                created_ts  REAL,
                hit_count   INTEGER DEFAULT 0
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_cache_model ON llm_cache(model)"
        )
        self._conn.commit()

    # ---- embeddings --------------------------------------------------------

    @staticmethod
    def _embed_local(text: str, dim: int = 384) -> "np.ndarray":
        """Embedding determinista de emergencia (sin servicio): dispersión de
        shingles de 3-gramas hasheados. Solo útil para coincidencia casi exacta,
        pero mantiene la caché operativa sin API."""
        v = _np().zeros(dim, dtype=_np().float32)
        tokens = text.lower().split()
        for i in range(max(1, len(tokens) - 2)):
            gram = " ".join(tokens[i:i + 3])
            idx = int(hashlib.sha256(gram.encode()).hexdigest()[:8], 16) % dim
            v[idx] += 1.0
        norm = float(_np().linalg.norm(v))
        return v / norm if norm > 0 else v

    def _embed(self, text: str) -> "np.ndarray":
        """Embedding del contenido. Usa Gemini embed_content si está disponible;
        si no, fallback local determinista. NUNCA lanza."""
        if self._embed_fn is not None:
            return self._embed_fn(text)
        try:
            from google import genai
            from config import GEMINI_API_KEY
            if not GEMINI_API_KEY:
                raise RuntimeError("sin api key")
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.embed_content(
                model="text-embedding-004", contents=text
            )
            arr = _np().asarray(resp.embeddings.values, dtype=_np().float32) \
                if hasattr(resp, "embeddings") else _np().asarray(resp.embedding.values, dtype=_np().float32)
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            vec = arr[0]
            norm = float(_np().linalg.norm(vec))
            return vec / norm if norm > 0 else vec
        except Exception:
            return self._embed_local(text)

    @staticmethod
    def _prompt_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join(text.split()).strip()

    # ---- índice FAISS ------------------------------------------------------

    def _build_index(self, model: str, kind: str) -> None:
        rows = self._conn.execute(
            "SELECT id, embedding FROM llm_cache WHERE model=? AND kind=?",
            (model, kind),
        ).fetchall()
        vecs = []
        ids = []
        for r in rows:
            if r["embedding"] is None:
                continue
            v = _np().frombuffer(r["embedding"], dtype=_np().float32)
            if v.size == 0:
                continue
            vecs.append(v)
            ids.append(r["id"])
        if vecs:
            import faiss
            mat = _np().stack(vecs).astype(_np().float32)
            index = faiss.IndexFlatIP(mat.shape[1])
            index.add(mat)
            self._index = index
        else:
            self._index = None
        self._index_ids = ids
        self._index_model = (model, kind)

    def _ensure_index(self, model: str, kind: str) -> None:
        if (self._index is None or self._index_model != (model, kind)
                or len(self._index_ids) != self._n_rows(model, kind)):
            self._build_index(model, kind)

    def _n_rows(self, model: str, kind: str) -> int:
        r = self._conn.execute(
            "SELECT COUNT(*) AS c FROM llm_cache WHERE model=? AND kind=?",
            (model, kind),
        ).fetchone()
        return int(r["c"])

    # ---- API pública -------------------------------------------------------

    def get(self, prompt: str, model: str, kind: str = "text"):
        """Devuelve la respuesta cacheada si el embedding más cercano supera el
        umbral. Retorna dict o None."""
        norm = self._norm(prompt)
        self._ensure_index(model, kind)
        if self._index is None or not self._index_ids:
            self.misses += 1
            return None
        vec = self._embed(norm).reshape(1, -1).astype(_np().float32)
        scores, idxs = self._index.search(vec, 1)
        best_score = float(scores[0][0])
        if best_score < self.threshold:
            self.misses += 1
            return None
        row_id = self._index_ids[int(idxs[0][0])]
        row = self._conn.execute(
            "SELECT * FROM llm_cache WHERE id=?", (row_id,)
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        if self.ttl_days and row["created_ts"] and \
                (time.time() - row["created_ts"]) > self.ttl_days * 86400:
            self.misses += 1
            return None
        self._conn.execute(
            "UPDATE llm_cache SET hit_count=hit_count+1 WHERE id=?", (row_id,)
        )
        self._conn.commit()
        self.hits += 1
        return {
            "response": row["response"],
            "tool_calls": json.loads(row["tool_calls"]) if row["tool_calls"] else None,
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "similarity": best_score,
        }

    def put(self, prompt: str, model: str, kind: str, response: str,
            tool_calls=None, input_tokens: int = 0, output_tokens: int = 0,
            cost_usd: float = 0.0) -> None:
        norm = self._norm(prompt)
        vec = self._embed(norm)
        blob = vec.astype(_np().float32).tobytes()
        self._conn.execute(
            "INSERT INTO llm_cache "
            "(prompt_hash, model, kind, embedding, response, tool_calls, "
            " input_tokens, output_tokens, created_ts, hit_count) "
            "VALUES (?,?,?,?,?,?,?,?,?,0)",
            (self._prompt_hash(norm), model, kind, blob, response,
             json.dumps(tool_calls) if tool_calls is not None else None,
             input_tokens, output_tokens, time.time()),
        )
        self._conn.commit()
        self._index = None  # invalidar índice para reconstruirlo con el nuevo
        self._index_model = None

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses,
                "cost_saved_usd": round(self.cost_saved_usd, 4)}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def default_cache() -> LLMCache | None:
    """Caché global (singleton ligero). None si está deshabilitada en config."""
    from config import LLM_CACHE_ENABLED
    if not LLM_CACHE_ENABLED:
        return None
    try:
        return LLMCache()
    except Exception:
        return None
