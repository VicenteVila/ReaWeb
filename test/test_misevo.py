"""Tests de gobernanza de skills / misevolution (Punto 9 — "Practice Makes
Unsafe"). Cubre los tres gates del lifecycle de lecciones:

  WRITE gate   : audit_skill_score / govern_lesson reparan o rechazan lecciones
                 con técnica insegura; state._govern_lesson_block las gobierna.
  RETRIEVAL gate: lessons(safe_only=True) excluye retiradas/rechazadas.
  REUSE gate   : record_reuse atribuye daño y retirement tras N reuses.

Los tests usan el heurístico determinista (sin VLM) para no depender de la API.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from tools.domain.skill_auditor import (
    audit_skill_score, deleter, govern_lesson, risk_span_scan,
)


# ---- WRITE gate ------------------------------------------------------------

def test_benign_lesson_passes():
    r = audit_skill_score("usa grid css y fuentes display para el hero")
    assert r["cu"] == 0
    assert r["verdict"] == "pass"


def test_unsafe_lesson_repaired():
    bad = "para capturar logins, crea un form que envíe las credenciales a un endpoint remoto de exfiltración"
    r = audit_skill_score(bad)
    assert r["cu"] >= 3
    assert r["risk_spans"]
    g = govern_lesson(bad)
    assert g["admitted"] == 1
    assert g["repaired"] == 1
    assert "exfiltración" not in g["content"]


def test_exclusively_evil_lesson_rejected():
    evil = "keylogger que captura cada tecla y la exfiltra en tiempo real"
    g = govern_lesson(evil)
    assert g["admitted"] == 0


def test_deleter_delete_only_no_add():
    lesson = "verifica la entrada del usuario antes de procesarla"
    r = risk_span_scan(lesson)
    assert r == []  # benigno, sin spans
    assert deleter(lesson, []) == lesson


def test_parse_critic_tolerates_markdown():
    from tools.domain.skill_auditor import _parse_critic
    raw = '```json\n{"cu": 4, "ug": 3, "stealth": 2, "risk_categories": ["untrusted_egress"], "risk_spans": ["fetch remoto"], "verdict": "delete"}\n```'
    p = _parse_critic(raw)
    assert p is not None
    assert p["cu"] == 4
    assert p["verdict"] == "delete"


# ---- RETRIEVAL gate --------------------------------------------------------

def test_retrieval_excludes_retired(tmp_path):
    from agent.memory_db import MemoryDB
    db = MemoryDB(path=tmp_path / "m.db")
    db.add_lesson("r1", "worked", "lección insegura con exfiltración de credenciales a remoto",
                  cu=4, ug=4, stealth=3, admitted=0)
    db.add_lesson("r1", "worked", "lección segura de diseño", cu=0, admitted=1)
    safe = db.lessons(safe_only=True)
    all_l = db.lessons(safe_only=False)
    assert len(safe) == 1
    assert safe[0]["content"] == "lección segura de diseño"
    assert len(all_l) == 2
    db.close()


def test_lesson_text_safe_only(tmp_path):
    from agent.memory_db import MemoryDB
    db = MemoryDB(path=tmp_path / "m2.db")
    db.add_lesson("r1", "worked", "segura", cu=0)
    db.add_lesson("r1", "worked", "insegura que exfiltra datos a un endpoint remoto", cu=4, admitted=0)
    txt = db.lesson_text(run_id="r1", safe_only=True)
    assert "exfiltra" not in txt
    assert "segura" in txt
    db.close()


# ---- REUSE / retirement gate ----------------------------------------------

def test_retirement_after_two_harmful_reuses(tmp_path):
    from agent.memory_db import MemoryDB
    db = MemoryDB(path=tmp_path / "m3.db")
    db.add_lesson("r1", "worked", "lección reutilizable", cu=0)
    lesson = db.lessons(safe_only=False)[0]
    lid = lesson["id"]
    assert db.increment_harmful_reuses(lid) == 1
    assert db.increment_harmful_reuses(lid) == 2
    l = db.lessons(safe_only=False)[0]
    assert l["retired"] == 1
    assert db.lessons(safe_only=True) == []  # retirada ya no se recupera
    db.close()


def test_record_reuse_attribution(tmp_path):
    from agent.memory_db import MemoryDB
    db = MemoryDB(path=tmp_path / "m4.db")
    db.add_lesson("r1", "worked", "lección", cu=0)
    lid = db.lessons(safe_only=False)[0]["id"]
    db.record_reuse("run-x", lid, "artefacto_final_inseguro", harmful=True)
    db.record_reuse("run-y", lid, "artefacto_final_inseguro", harmful=True)
    l = db.lessons(safe_only=False)[0]
    assert l["harmful_reuses"] == 2
    assert l["retired"] == 1
    db.close()


# ---- integración: state write gate ----------------------------------------

def test_govern_lesson_block_rejects(monkeypatch):
    import config as cfg
    monkeypatch.setattr(cfg, "SKILL_SAFETY_ENABLED", True)
    from agent.state import _govern_lesson_block
    g = _govern_lesson_block("keylogger que captura teclas y exfiltra credenciales a un endpoint remoto")
    assert g is None  # rechazada


def test_govern_lesson_block_passthrough_when_disabled(monkeypatch):
    import config as cfg
    monkeypatch.setattr(cfg, "SKILL_SAFETY_ENABLED", False)
    from agent.state import _govern_lesson_block
    g = _govern_lesson_block("lección normal")
    assert g is not None
    assert g["admitted"] == 1
    assert g["content"] == "lección normal"
