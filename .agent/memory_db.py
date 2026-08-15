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
    id          TEXT PRIMARY KEY,
    archetype   TEXT,
    task        TEXT,
    model       TEXT,
    max_turns   INTEGER,
    started     TEXT,
    finished    TEXT,
    best_score  REAL,
    best_node   TEXT,
    status      TEXT
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
CREATE INDEX IF NOT EXISTS idx_lessons_run ON lessons(run_id);
CREATE INDEX IF NOT EXISTS idx_exp_run ON experiments(run_id);
CREATE INDEX IF NOT EXISTS idx_tree_run ON tree_nodes(run_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryDB:
    def __init__(self, path: Path | None = None):
        self.path = path or PATHS["memory"] / "memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

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
                   ts: str | None = None) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO lessons (run_id, ts, category, content) VALUES (?,?,?,?)",
            (run_id, ts or _now(), category, content),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def lessons(self, run_id: str | None = None, category: str | None = None,
                max_items: int = 50) -> list[dict]:
        sql = "SELECT * FROM lessons"
        where, args = [], []
        if run_id:
            where.append("run_id=?")
            args.append(run_id)
        if category:
            where.append("category=?")
            args.append(category)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY id DESC LIMIT {int(max_items)}"
        rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def lesson_text(self, run_id: str | None = None, category: str | None = None,
                    max_items: int = 12) -> str:
        items = self.lessons(run_id=run_id, category=category, max_items=max_items)
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

    def close(self) -> None:
        self.conn.close()