"""Tests de Task-CoEvolve (Punto 10): selección adaptativa de tareas de
validación con estimación sampling-aware del score full-suite.

Referencia: Miyai et al. (2026), arXiv:2608.20169 (adaptación continua a
scores 0-100 en ReaWeb)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory_db import MemoryDB
from tools.domain.task_coevolve import (
    SelectionResult,
    TaskSelector,
    adaptive_tasks_from_db,
    load_history,
    task_stats,
    task_weight,
)

HIST_DISCORDANTE = {"t1": [0.2, 0.8, 0.3, 0.9]}       # candidatos discrepan
HIST_CONSENSO = {"t2": [0.85, 0.85, 0.85, 0.85]}      # todos la resuelven igual


def _selector(history=None, **kw) -> TaskSelector:
    return TaskSelector(history or {}, mc_reps=kw.pop("mc_reps", 500), **kw)


# --- pesos (Eq. 2 adaptada a scores continuos) ---

def test_weight_peaks_at_disagreement():
    st_d = task_stats(HIST_DISCORDANTE)["t1"]
    st_c = task_stats(HIST_CONSENSO)["t2"]
    assert task_weight(**st_d) > task_weight(**st_c)
    # consenso total => var=0; solo queda el bonus de incertidumbre
    assert task_weight(st_c["mean"], st_c["var"], st_c["n"]) <= 0.025 / 2 + 1e-9


def test_weight_unseen_task_gets_floor_and_bonus():
    w = task_weight(None, None, 0)
    assert w > 0.125  # suelo l + bonus: una tarea nueva no se excluye sola


def test_weight_uncertainty_bonus_decreases_with_n():
    st = task_stats(HIST_DISCORDANTE)["t1"]
    assert task_weight(st["mean"], st["var"], 1) > task_weight(st["mean"], st["var"], 100)


# --- selección y π_t ---

def test_select_size_is_ceil_rho_n():
    sel = _selector().select([f"t{i}" for i in range(10)], rho=0.5)
    assert len(sel.selected) == 5


def test_sampling_deterministic_given_seed():
    pool = [f"t{i}" for i in range(12)]
    a = _selector(seed=7).select(pool, rho=0.5)
    b = _selector(seed=7).select(pool, rho=0.5)
    c = _selector(seed=99).select(pool, rho=0.5)
    assert a.selected == b.selected != c.selected


def test_inclusion_probabilities_sum_to_m():
    sel = _selector().select([f"t{i}" for i in range(10)], rho=0.4)
    assert abs(sum(sel.inclusion_probs.values()) - len(sel.selected)) < 0.05


def test_discordant_task_sampled_more_often():
    history = dict(HIST_DISCORDANTE)
    for i in range(6):
        history[f"easy{i}"] = [0.9] * 4
    sel = _selector(history, mc_reps=800).select(list(history), rho=0.25)
    assert sel.weights["t1"] > max(sel.weights[e] for e in history if e != "t1")


def test_empty_history_behaves_like_uniform_resample():
    sel = _selector({}).select([f"t{i}" for i in range(8)], rho=0.5)
    for p in sel.inclusion_probs.values():
        assert abs(p - 0.5) < 0.08


# --- estimadores (Eqs. 3-4 y regla del §3.3) ---

def test_estimator_rule_extremes_vs_middle():
    assert TaskSelector.choose_estimator(0.05) == "hajek"
    assert TaskSelector.choose_estimator(0.95) == "hajek"
    assert TaskSelector.choose_estimator(0.5) == "anchored"


def test_hajek_unbiased_under_uniform_sampling():
    scores = {f"t{i}": i / 10 for i in range(10)}
    anchors = {t: 0.5 for t in scores}
    pi = {t: 0.5 for t in scores}
    sel = SelectionResult(selected=list(scores), inclusion_probs=pi,
                          anchors=anchors, estimator="hajek", pool_mean=0.45)
    est = _selector().estimate(scores, sel, pool_size=10)
    assert abs(est - sum(scores.values()) / 10) < 1e-9


def test_anchored_zero_deviation_returns_anchor_mean():
    anchors = {t: v for t, v in zip("abc", (0.2, 0.5, 0.8))}
    sel = SelectionResult(selected=["a"], inclusion_probs={"a": 0.5},
                          anchors=anchors, estimator="anchored", pool_mean=0.5)
    # outcome igual al ancla => contribución nula => Ŝ = media de anclas
    est = _selector().estimate({"a": 0.2}, sel, pool_size=3)
    assert abs(est - 0.5) < 1e-9


def test_anchored_absorbs_easy_rarely_sampled_task():
    """Caso del Apéndice A.2: una tarea fácil con ancla alto y π pequeña no debe
    disparar la estimación (eso es lo que arregla el ancla frente a Hájek)."""
    anchors = {"hard": 0.0, "easy": 1.0}  # solo se muestrea la fácil (π=1/3)
    sel = SelectionResult(selected=["easy"], inclusion_probs={"easy": 1/3},
                          anchors=anchors, estimator="anchored", pool_mean=0.5)
    est_anch = _selector().estimate({"easy": 1.0}, sel, pool_size=2)
    sel_h = SelectionResult(selected=["easy"], inclusion_probs={"easy": 1/3},
                            anchors=anchors, estimator="hajek", pool_mean=0.5)
    est_hajek = _selector().estimate({"easy": 1.0}, sel_h, pool_size=2)
    assert abs(est_hajek - 1.0) < 1e-9   # Hájek satura: x/π domina la suma
    assert abs(est_anch - 0.5) < 1e-9    # el anclado absorbe la desviación nula


# --- persistencia en memory.db ---

def test_task_evals_roundtrip_and_history(tmp_path):
    db = MemoryDB(path=tmp_path / "mem.db")
    db.add_task_eval(run_id="r1", task_id="landing-x", task_hash="hash-a",
                     archetype="landing-page", task="Tarea A", score=80.0,
                     baseline=70.0)
    db.add_task_eval(run_id="r2", task_id="ecommerce-y", task_hash="hash-b",
                     archetype="ecommerce", task="Tarea B", score=90.0)
    rows = db.task_evals(task_hash="hash-a")
    assert len(rows) == 1 and rows[0]["score"] == 80.0
    hist = load_history(db)
    assert hist["hash-a"] == [0.8] and hist["hash-b"] == [0.9]
    db.close()


def test_adaptive_tasks_prefers_variance_and_diversity(tmp_path):
    db = MemoryDB(path=tmp_path / "mem.db")
    # t-var discrepa entre runs; t-flat no discrimina
    db.add_task_eval(None, "t-var", "h1", "landing-page", "Varia mucho", 40.0)
    db.add_task_eval(None, "t-var", "h1", "landing-page", "Varia mucho", 95.0)
    db.add_task_eval(None, "t-flat", "h2", "ecommerce", "Plana", 85.0)
    db.add_task_eval(None, "t-flat", "h2", "ecommerce", "Plana", 86.0)
    db.add_task_eval(None, "t-dev", "h3", "blog-content", "Dev razonable", 60.0)
    db.add_task_eval(None, "t-dev", "h3", "blog-content", "Dev razonable", 75.0)
    picked = adaptive_tasks_from_db(db, k=2)
    ids = [p["task_id"] for p in picked]
    assert ids[0] == "t-var"
    assert "t-flat" not in ids          # varianza casi nula => último puesto
    assert picked[0]["archetype"] != picked[1]["archetype"]  # diversidad
    db.close()


def test_adaptive_tasks_empty_history_falls_back(tmp_path):
    db = MemoryDB(path=tmp_path / "mem.db")
    assert adaptive_tasks_from_db(db, k=2) == []
    db.close()
