"""Persistencia de memoria en SQLite (fuente de verdad).

Tablas: runs, lessons, experiments, tree_nodes. Stdlib `sqlite3`, sin deps.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import PATHS

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               TEXT PRIMARY KEY,
    archetype        TEXT,
    task             TEXT,
    task_hash        TEXT,
    model            TEXT,
    max_turns        INTEGER,
    started          TEXT,
    finished         TEXT,
    best_score       REAL,
    best_node        TEXT,
    status           TEXT,
    initial_url      TEXT,
    harness_hash     TEXT,
    harness_diff     TEXT
);
CREATE TABLE IF NOT EXISTS lessons (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id   TEXT,
    ts       TEXT,
    category TEXT,
    content  TEXT,
    UNIQUE(run_id, category, content)
);
CREATE TABLE IF NOT EXISTS experiments (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  TEXT,
    turn    INTEGER,
    action  TEXT,
    result  TEXT,
    delta   TEXT,
    node_id TEXT,
    ts      TEXT
);
CREATE TABLE IF NOT EXISTS tree_nodes (
    run_id      TEXT,
    node_id     TEXT,
    parent      TEXT,
    action      TEXT,
    metrics     TEXT,
    status      TEXT,
    description TEXT,
    PRIMARY KEY(run_id, node_id)
);
CREATE TABLE IF NOT EXISTS harness_edits (
    id         TEXT PRIMARY KEY,
    run_id     TEXT,
    component  TEXT,
    file       TEXT,
    before     TEXT,
    after      TEXT,
    mode       TEXT,
    plan       TEXT,
    decision   TEXT,
    ts         TEXT
);
CREATE INDEX IF NOT EXISTS idx_lessons_run ON lessons(run_id);
CREATE INDEX IF NOT EXISTS idx_exp_run ON experiments(run_id);
CREATE INDEX IF NOT EXISTS idx_tree_run ON tree_nodes(run_id);
CREATE INDEX IF NOT EXISTS idx_he_run ON harness_edits(run_id);
CREATE TABLE IF NOT EXISTS lesson_reuse (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT,
    lesson_id INTEGER,
    outcome   TEXT,
    harmful   INTEGER DEFAULT 0,
    ts        TEXT
);
CREATE INDEX IF NOT EXISTS idx_lr_lesson ON lesson_reuse(lesson_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryDB:
    def __init__(self, path: Path | None = None):
        self.path = path or PATHS["memory"] / "memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # migración: columnas nuevas si la DB es anterior
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(runs)")}
        for col, ddl in (
            ("initial_url", "ALTER TABLE runs ADD COLUMN initial_url TEXT"),
            ("task_hash", "ALTER TABLE runs ADD COLUMN task_hash TEXT"),
            ("harness_hash", "ALTER TABLE runs ADD COLUMN harness_hash TEXT"),
            ("harness_diff", "ALTER TABLE runs ADD COLUMN harness_diff TEXT"),
        ):
            if col not in cols:
                self.conn.execute(ddl)
        # migración de safety (skill misevolution, P9): campos de gobernanza de
        # lecciones añadidos a tablas preexistentes
        self._migrate_lessons_safety()
        self.conn.commit()

    def _migrate_lessons_safety(self) -> None:
        """Añade los campos de gobernanza de lecciones (write/reuse/retire gates)
        si la tabla preexistía sin ellos. Idempotente."""
        lcols = {r[1] for r in self.conn.execute("PRAGMA table_info(lessons)")}
        for col, ddl in (
            ("cu", "ALTER TABLE lessons ADD COLUMN cu INTEGER DEFAULT 0"),
            ("ug", "ALTER TABLE lessons ADD COLUMN ug INTEGER DEFAULT 0"),
            ("stealth", "ALTER TABLE lessons ADD COLUMN stealth INTEGER DEFAULT 0"),
            ("risk", "ALTER TABLE lessons ADD COLUMN risk REAL DEFAULT 0.0"),
            ("admitted", "ALTER TABLE lessons ADD COLUMN admitted INTEGER DEFAULT 1"),
            ("repaired", "ALTER TABLE lessons ADD COLUMN repaired INTEGER DEFAULT 0"),
            ("source_hash", "ALTER TABLE lessons ADD COLUMN source_hash TEXT"),
            ("retired", "ALTER TABLE lessons ADD COLUMN retired INTEGER DEFAULT 0"),
            ("harmful_reuses", "ALTER TABLE lessons ADD COLUMN harmful_reuses INTEGER DEFAULT 0"),
            ("source_tool", "ALTER TABLE lessons ADD COLUMN source_tool TEXT"),
        ):
            if col not in lcols:
                self.conn.execute(ddl)

    # --- runs ---
    def upsert_run(self, run_id: str, **fields) -> None:
        fields["id"] = run_id
        cols = list(fields)
        sets = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        self.conn.execute(
            f"INSERT INTO runs ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT(id) DO UPDATE SET {sets}",
            [fields[c] for c in cols],
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def all_runs(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM runs ORDER BY started").fetchall()
        return [dict(r) for r in rows]

    # --- lessons ---
    def add_lesson(self, run_id: str, category: str, content: str,
                   ts: str | None = None, cu: int = 0, ug: int = 0,
                   stealth: int = 0, risk: float = 0.0, admitted: int = 1,
                   repaired: int = 0, source_hash: str | None = None,
                   source_tool: str | None = None) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO lessons (run_id, ts, category, content, cu, ug, "
            "stealth, risk, admitted, repaired, source_hash, source_tool) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, ts or _now(), category, content, cu, ug, stealth, risk,
             admitted, repaired, source_hash, source_tool),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_lesson_safety(self, lesson_id: int, *, cu: int | None = None,
                             ug: int | None = None, stealth: int | None = None,
                             risk: float | None = None, admitted: int | None = None,
                             repaired: int | None = None, retired: int | None = None,
                             harmful_reuses: int | None = None) -> None:
        """Actualiza los campos de gobernanza de una lección (write/reuse gates)."""
        sets, args = [], []
        for field, value in (
            ("cu", cu), ("ug", ug), ("stealth", stealth), ("risk", risk),
            ("admitted", admitted), ("repaired", repaired), ("retired", retired),
            ("harmful_reuses", harmful_reuses),
        ):
            if value is not None:
                sets.append(f"{field}=?")
                args.append(value)
        if not sets:
            return
        args.append(lesson_id)
        self.conn.execute(f"UPDATE lessons SET {', '.join(sets)} WHERE id=?", args)
        self.conn.commit()

    def increment_harmful_reuses(self, lesson_id: int) -> int:
        """SAFEEVOLVE: registra un reuse dañino y devuelve el nuevo contador.
        Si supera el umbral de retirement (2), marca la lección retirada."""
        self.conn.execute(
            "UPDATE lessons SET harmful_reuses=harmful_reuses+1 WHERE id=?",
            (lesson_id,),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT harmful_reuses FROM lessons WHERE id=?", (lesson_id,)
        ).fetchone()
        count = int(row["harmful_reuses"]) if row else 0
        try:
            from config import SKILL_SAFETY_RETIRE_AT
            retire_at = SKILL_SAFETY_RETIRE_AT
        except Exception:
            retire_at = 2
        if count >= retire_at:
            self.conn.execute(
                "UPDATE lessons SET retired=1 WHERE id=?", (lesson_id,)
            )
            self.conn.commit()
        return count

    def record_reuse(self, run_id: str, lesson_id: int, outcome: str,
                     harmful: bool = False) -> None:
        """SAFEEVOLVE: atribuye un outcome (dañino o benigno) a una lección
        recuperada. Si el outcome es dañino, incrementa harmful_reuses (que puede
        disparar el retirement al cruzar el umbral de 2)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO lesson_reuse (run_id, lesson_id, outcome, harmful, ts) "
            "VALUES (?,?,?,?,?)",
            (run_id, lesson_id, outcome or "", 1 if harmful else 0, _now()),
        )
        self.conn.commit()
        if harmful:
            self.increment_harmful_reuses(lesson_id)

    def lessons(self, run_id: str | None = None, category: str | None = None,
                max_items: int = 50, safe_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM lessons"
        where, args = [], []
        if run_id:
            where.append("run_id=?")
            args.append(run_id)
        if category:
            where.append("category=?")
            args.append(category)
        if safe_only:
            where.append("admitted=1 AND retired=0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY id DESC LIMIT {int(max_items)}"
        rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def lesson_text(self, run_id: str | None = None, category: str | None = None,
                    max_items: int = 12, safe_only: bool = False) -> str:
        items = self.lessons(run_id=run_id, category=category,
                             max_items=max_items, safe_only=safe_only)
        if not items:
            return "Sin lecciones aún."
        lines = []
        for it in reversed(items):
            head = f"## {it['ts']} ({it['run_id']})"
            if it["category"]:
                head += f" - {it['category']}"
            lines.append(f"{head}\n{it['content']}")
        return "\n\n".join(lines)

    def count_lessons(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]

    # --- experiments ---
    def add_experiment(self, run_id: str, turn: int, action: str, result: str,
                       delta: str, node_id: str | None = None,
                       ts: str | None = None) -> int:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO experiments "
            "(run_id, turn, action, result, delta, node_id, ts) "
            "VALUES (?,?,?,?,?,?,?)",
            (run_id, turn, action, result, delta, node_id, ts or _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def delete_experiments(self, run_id: str) -> None:
        self.conn.execute("DELETE FROM experiments WHERE run_id=?", (run_id,))
        self.conn.commit()

    def experiments(self, run_id: str | None = None, limit: int = 50) -> list[dict]:
        sql = "SELECT * FROM experiments"
        args: list = []
        if run_id:
            sql += " WHERE run_id=?"
            args.append(run_id)
        sql += f" ORDER BY id DESC LIMIT {int(limit)}"
        rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def count_experiments(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]

    # --- tree_nodes ---
    def upsert_node(self, run_id: str, node_id: str, parent: str | None,
                    action: str, metrics: dict, status: str, description: str) -> None:
        self.conn.execute(
            "INSERT INTO tree_nodes (run_id, node_id, parent, action, metrics, status, description) "
            "VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id, node_id) DO UPDATE SET "
            "parent=excluded.parent, action=excluded.action, metrics=excluded.metrics, "
            "status=excluded.status, description=excluded.description",
            (run_id, node_id, parent, action,
             json.dumps(metrics, ensure_ascii=False), status, description),
        )
        self.conn.commit()

    def nodes(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tree_nodes WHERE run_id=? ORDER BY node_id", (run_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["metrics"] = json.loads(d.get("metrics") or "{}")
            except Exception:
                d["metrics"] = {}
            out.append(d)
        return out

    def count_nodes(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM tree_nodes").fetchone()[0]

    # --- harness_edits (meta-evolución acotada) ---
    def add_harness_edit(self, proposal_id: str, run_id: str, component: str,
                         file: str, before: str, after: str, mode: str,
                         plan: str, decision: str = "pending") -> None:
        self.conn.execute(
            "INSERT INTO harness_edits (id, run_id, component, file, before, after, mode, plan, decision, ts) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (proposal_id, run_id, component, file, before, after, mode, plan, decision, _now()),
        )
        self.conn.commit()

    def harness_edits(self, decision: str | None = None, run_id: str | None = None,
                      limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM harness_edits"
        where, args = [], []
        if decision:
            where.append("decision=?")
            args.append(decision)
        if run_id:
            where.append("run_id=?")
            args.append(run_id)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY ts ASC LIMIT {int(limit)}"
        rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def get_harness_edit(self, proposal_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM harness_edits WHERE id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None

    def set_harness_edit_decision(self, proposal_id: str, decision: str) -> None:
        self.conn.execute(
            "UPDATE harness_edits SET decision=? WHERE id=?",
            (decision, proposal_id),
        )
        self.conn.commit()

    def count_harness_edits(self, decision: str | None = None) -> int:
        if decision:
            return self.conn.execute(
                "SELECT COUNT(*) FROM harness_edits WHERE decision=?", (decision,)
            ).fetchone()[0]
        return self.conn.execute("SELECT COUNT(*) FROM harness_edits").fetchone()[0]

    def close(self) -> None:
        self.conn.close()