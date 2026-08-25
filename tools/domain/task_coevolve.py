"""Task-CoEvolve (Punto 10): selección adaptativa de tareas de validación.

Adaptación de: Miyai, A., Aizawa, K. & Yamasaki, T. (2026). "Task-CoEvolve:
Efficient Harness Optimization via Adaptive Validation Task Selection".
arXiv:2608.20169.

El paper co-evoluciona las tareas de validación con el harness para no evaluar
el pool completo en cada iteración. Dos componentes:

1. Variance-weighted selection (Eq. 2): w_t = max(p̄_t(1-p̄_t), ℓ_t) + λ/√n_t.
   En ReaWeb el outcome es continuo (score 0-100 normalizado a [0,1]), así que
   la varianza de Bernoulli se sustituye por la varianza muestral del score
   histórico: sigue siendo máxima cuando los candidatos discrepan sobre la
   tarea y ~0 cuando todos puntúan igual (tarea no discriminativa).
2. Sampling-aware full-set estimation (Eqs. 3-4): estimar el score full-set
   desde el subconjunto muestreado corrigiendo por la probabilidad de inclusión
   π_t (Horvitz-Thompson), con dos formas según la estructura del pool:
   - Hájek (Eq. 3) si los anchors históricos viven cerca de 0 o de 1.
   - Diferencia anclada (Eq. 4) si viven en la zona media (caso típico ReaWeb).

Todo depende solo de outcomes observados (scores históricos), sin asumir nada
sobre el contenido de la tarea ni del harness.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

try:
    from config import (
        TASK_COEVOLVE_L,
        TASK_COEVOLVE_LAMBDA,
        TASK_COEVOLVE_MC_REPS,
        TASK_COEVOLVE_RHO,
        TASK_COEVOLVE_SEED,
    )
except Exception:  # fallback si config aún no define Punto 10
    TASK_COEVOLVE_RHO = 0.5
    TASK_COEVOLVE_L = 0.125
    TASK_COEVOLVE_LAMBDA = 0.025
    TASK_COEVOLVE_MC_REPS = 4000
    TASK_COEVOLVE_SEED = 13


def task_weight(mean: float | None, var: float | None, n: int,
                l: float = TASK_COEVOLVE_L,
                lam: float = TASK_COEVOLVE_LAMBDA) -> float:
    """Peso de muestreo de una tarea (adaptación continua de la Eq. 2).

    - ``var``: varianza de los scores históricos en [0,1]; máxima cuando los
      candidatos discrepan. Tarea nunca evaluada (n=0) recibe el suelo ℓ para
      no quedar excluida antes de su primera señal.
    - ``lam / sqrt(n)`` (con n>=1; n=0 usa 1): bonus de incertidumbre que
      protege a las tareas con pocas observaciones.
    """
    base = var if (var is not None and n > 0) else l
    return max(base, 0.0) + lam / math.sqrt(max(n, 1))


def task_stats(history: dict[str, list[float]]) -> dict[str, dict]:
    """De {task_id: [scores 0-1]} a {task_id: {mean, var, n}}.

    Varianza poblacional (como la Bernoulli p(1-p) del paper, que también lo es).
    """
    stats = {}
    for tid, scores in history.items():
        vals = [float(s) for s in scores if s is not None]
        n = len(vals)
        if n == 0:
            stats[tid] = {"mean": None, "var": None, "n": 0}
            continue
        mean = sum(vals) / n
        var = sum((v - mean) ** 2 for v in vals) / n
        stats[tid] = {"mean": mean, "var": var, "n": n}
    return stats


@dataclass
class SelectionResult:
    """Resultado de una selección: subconjunto, π_t, pesos y anclas fijadas."""

    selected: list[str]
    inclusion_probs: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)
    anchors: dict[str, float] = field(default_factory=dict)
    estimator: str = "anchored"          # "hajek" | "anchored"
    pool_mean: float = 0.5
    rho: float = TASK_COEVOLVE_RHO
    stats: dict[str, dict] = field(default_factory=dict)


class TaskSelector:
    """Selecciona un subconjunto de validación y estima el score full-set."""

    def __init__(self, history: dict[str, list[float]],
                 rho: float | None = None, l: float | None = None,
                 lam: float | None = None, mc_reps: int | None = None,
                 seed: int | None = None):
        self.rho = TASK_COEVOLVE_RHO if rho is None else rho
        self.l = TASK_COEVOLVE_L if l is None else l
        self.lam = TASK_COEVOLVE_LAMBDA if lam is None else lam
        self.mc_reps = mc_reps or TASK_COEVOLVE_MC_REPS
        self.seed = TASK_COEVOLVE_SEED if seed is None else seed
        self.history = history or {}
        self.stats = task_stats(self.history)

    # --- Fase 1: variance-weighted selection ---
    def weights_for(self, pool: list[str]) -> dict[str, float]:
        out = {}
        for t in pool:
            st = self.stats.get(t, {"mean": None, "var": None, "n": 0})
            out[t] = task_weight(st["mean"], st["var"], st["n"],
                                 l=self.l, lam=self.lam)
        return out

    def _draw(self, weights: dict[str, float], m: int,
              rng: random.Random) -> set[str]:
        """Muestreo sin reemplazo ponderado (Efraimidis-Spirakis)."""
        keys = {t: rng.random() ** (1.0 / max(w, 1e-12))
                for t, w in weights.items()}
        return set(sorted(keys, key=lambda t: keys[t], reverse=True)[:m])

    def select(self, pool: list[str], rho: float | None = None) -> SelectionResult:
        """Muestrea ⌈ρN⌉ tareas y estima π_t por Monte Carlo."""
        r = self.rho if rho is None else rho
        r = min(max(r, 1e-6), 1.0)
        n = len(pool)
        m = min(n, max(2, math.ceil(r * n))) if n > 2 else n
        weights = self.weights_for(pool)

        rng = random.Random(self.seed)
        selected = sorted(self._draw(weights, m, random.Random(self.seed)))

        counts = {t: 0 for t in pool}
        reps = max(1, self.mc_reps)
        for _ in range(reps):
            for t in self._draw(weights, m, rng):
                counts[t] += 1
        pi = {t: counts[t] / reps for t in pool}

        anchors = {}
        known = [self.stats[t]["mean"] for t in pool
                 if self.stats.get(t, {}).get("mean") is not None]
        pool_mean = sum(known) / len(known) if known else 0.5
        for t in pool:
            mu = self.stats.get(t, {}).get("mean")
            anchors[t] = mu if mu is not None else pool_mean

        return SelectionResult(
            selected=selected,
            inclusion_probs=pi,
            weights=weights,
            anchors=anchors,
            estimator=self.choose_estimator(pool_mean),
            pool_mean=pool_mean,
            rho=r,
            stats={t: self.stats.get(t, {"mean": None, "var": None, "n": 0})
                   for t in pool},
        )

    # --- Regla del §3.3: forma del estimador según estructura del pool ---
    @staticmethod
    def choose_estimator(pool_mean: float) -> str:
        """Hájek si los anchors están pegados a 0/1 (un outlier muestreado poco
        sigue cerca de la media del pool); diferencia anclada en zona media
        (evita que x_t/π_t domine la suma)."""
        if pool_mean <= 0.25 or pool_mean >= 0.75:
            return "hajek"
        return "anchored"

    # --- Fase 2: sampling-aware full-set estimation ---
    def estimate(self, sampled_scores: dict[str, float],
                 sel: SelectionResult, pool_size: int | None = None) -> float:
        """Ŝ(h) a partir de {task_id: score 0-1} del subconjunto evaluado."""
        n = pool_size or len(sel.inclusion_probs) or 1
        if not sampled_scores:
            return sel.pool_mean
        num = den = diff = 0.0
        for t, x in sampled_scores.items():
            p = sel.inclusion_probs.get(t) or 1.0
            num += x / p
            den += 1.0 / p
            diff += (x - sel.anchors.get(t, 0.0)) / p
        if sel.estimator == "hajek":
            return num / den if den else sel.pool_mean
        # Eq. 4: media de anclas + media de desviaciones ponderadas
        anchor_mean = (sum(sel.anchors.values()) / len(sel.anchors)
                       if sel.anchors else 0.0)
        return anchor_mean + diff / n

    def estimate_suite(self, sampled_scores: dict[str, float],
                       sel: SelectionResult,
                       pool_size: int | None = None) -> float:
        """Score full-suite estimado (0-100), conveniente para el leaderboard."""
        return round(100.0 * self.estimate(sampled_scores, sel,
                                           pool_size=pool_size), 1)


# --- Carga de historial desde memory.db ---

def load_history(db, hashes: list[str] | None = None) -> dict[str, list[float]]:
    """Historial {task_hash: [scores 0-1]} desde task_evals (+ runs como semilla).

    task_evals es la fuente fina (una fila por tarea evaluada); la tabla runs
    aporta un punto extra por run histórica anterior a Task-CoEvolve.
    """
    def _norm(score):
        return max(0.0, min(float(score) / 100.0, 1.0)) if score is not None else None

    rows = []
    try:
        rows = db.task_evals(limit=100000)
    except Exception:
        rows = []
    hist: dict[str, list[float]] = {}
    if rows:  # fuente fina: task_evals (una fila por tarea evaluada)
        for row in rows:
            th, s = row["task_hash"], _norm(row["score"])
            if th and s is not None and (not hashes or th in hashes):
                hist.setdefault(th, []).append(s)
        return hist

    # semilla pre-Task-CoEvolve: un punto por run histórica
    for r in db.all_runs():
        th, s = r.get("task_hash"), _norm(r.get("best_score"))
        if th and s is not None and (not hashes or th in hashes):
            hist.setdefault(th, []).append(s)
    return hist


def adaptive_tasks_from_db(db, k: int = 2,
                           exclude_ids: set[str] | None = None) -> list[dict]:
    """Devuelve las k tareas más discriminativas con historial, para el gate.

    Cada elemento: {task_id, archetype, task, weight}. Si no hay historial
    suficiente (<k tareas distintas), devuelve [] y el caller usa sus defaults.
    """
    rows = db.task_evals(limit=10000)
    by_text: dict[str, dict] = {}
    for r in rows:
        text = r.get("task") or ""
        if not text or (exclude_ids and r.get("task_id") in exclude_ids):
            continue
        e = by_text.setdefault(text, {
            "task_id": r.get("task_id"), "archetype": r.get("archetype"),
            "task": text, "scores": [],
        })
        if r.get("score") is not None:
            e["scores"].append(min(1.0, max(0.0, float(r["score"]) / 100.0)))
    history = {t: e.pop("scores") for t, e in by_text.items() if e["scores"]}
    for t, e in by_text.items():
        st = task_stats({t: history.get(t, [])})[t]
        e["weight"] = task_weight(st["mean"], st["var"], st["n"])
    ranked = sorted(by_text.values(), key=lambda e: -e["weight"])
    out: list[dict] = []
    archs = set()
    for e in ranked:
        if e["archetype"] in archs and len(out) < k:
            continue  # preferimos diversidad de arquetipo entre train/dev
        out.append(e)
        archs.add(e["archetype"])
        if len(out) == k:
            break
    if len(out) < k:  # relaja la restricción de arquetipo distinto
        for e in ranked:
            if e not in out:
                out.append(e)
                if len(out) == k:
                    break
    return out[:k]
