"""Estado del agente: árbol de búsqueda, memoria persistente (lessons.md) y
soporte para compresión de contexto."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import PATHS


@dataclass
class TreeNode:
    id: str
    parent: str | None
    action: str
    metrics: dict = field(default_factory=dict)
    status: str = "explored"  # explored | best_branch | dead_end
    description: str = ""


class SearchTree:
    def __init__(self, path: Path | None = None, run_id: str | None = None,
                 db: "MemoryDB | None" = None):
        self.path = path or PATHS["memory"] / "search_tree.json"
        self.run_id = run_id or (path.parent.name if path else None)
        self.db = db
        self.nodes: dict[str, TreeNode] = {}
        self.load()

    def load(self) -> None:
        if self.db is not None and self.run_id:
            for nd in self.db.nodes(self.run_id):
                node = TreeNode(
                    id=nd["node_id"],
                    parent=nd["parent"],
                    action=nd["action"],
                    metrics=nd.get("metrics", {}),
                    status=nd.get("status", "explored"),
                    description=nd.get("description", ""),
                )
                self.nodes[node.id] = node
            return
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                for node_id, nd in data.get("nodes", {}).items():
                    self.nodes[node_id] = TreeNode(**nd)
            except Exception:
                self.nodes = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"nodes": {nid: nd.__dict__ for nid, nd in self.nodes.items()}}
        self.path.write_text(json.dumps(data, indent=2))

    def add(self, node: TreeNode) -> None:
        self.nodes[node.id] = node
        if self.db is not None and self.run_id:
            self.db.upsert_node(
                run_id=self.run_id,
                node_id=node.id,
                parent=node.parent,
                action=node.action,
                metrics=node.metrics,
                status=node.status,
                description=node.description,
            )
        self.save()

    def best(self) -> TreeNode | None:
        best = None
        best_score = -1
        for nd in self.nodes.values():
            s = nd.metrics.get("total", -1)
            if s > best_score:
                best, best_score = nd, s
        return best

    def summary(self, max_nodes: int = 15) -> list[dict]:
        nodes = sorted(self.nodes.values(), key=lambda n: n.id)
        out = []
        for nd in nodes[-max_nodes:]:
            ms = ", ".join(f"{k}={v}" for k, v in sorted(nd.metrics.items()))
            out.append(
                {
                    "id": nd.id,
                    "parent": nd.parent,
                    "metrics_summary": ms or "sin métricas",
                    "status": nd.status,
                }
            )
        return out


@dataclass
class Experiment:
    id: str
    action: str
    result: str
    delta: str
    node_id: str | None = None


class Memory:
    def __init__(self, run_dir: Path | None = None, db: "MemoryDB | None" = None,
                 run_id: str | None = None):
        self.global_lessons = PATHS["memory"] / "lessons.md"
        self.run_dir = run_dir or PATHS["runs"]
        self.incremental = self.run_dir / "lessons_incremental.md"
        self.run_id = run_id or (self.run_dir.name if run_dir else None)
        self.db = db
        self.recent_experiments: list[Experiment] = []

    def read_global_lessons(self, max_items: int = 12) -> str:
        if self.db is not None:
            return self.db.lesson_text(run_id=None, max_items=max_items)
        if not self.global_lessons.exists():
            return "Sin lecciones aún."
        text = self.global_lessons.read_text()
        # Truco simple: recorta a los primeros max_items bloques ___.
        lines = text.splitlines()
        return "\n".join(lines[:])

    def append_global(self, text: str) -> None:
        if self.db is not None:
            # persiste cada bloque "## What <category> - <ts>" como lección deduplicada
            for category, content, ts in _parse_lesson_blocks(text):
                self.db.add_lesson(
                    run_id=self.run_id or "global", category=category,
                    content=content, ts=ts,
                )
            return
        self.global_lessons.parent.mkdir(parents=True, exist_ok=True)
        with self.global_lessons.open("a") as f:
            f.write(f"\n## {datetime.now().isoformat()}\n{text}\n")

    def append_incremental(self, text: str) -> None:
        if self.db is not None:
            for category, content, ts in _parse_lesson_blocks(text):
                self.db.add_lesson(
                    run_id=self.run_id or self.run_dir.name, category=category,
                    content=content, ts=ts,
                )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.incremental.open("a") as f:
            f.write(f"\n## {datetime.now().isoformat()}\n{text}\n")

    def add_experiment(self, exp: Experiment) -> None:
        self.recent_experiments.append(exp)
        self.recent_experiments = self.recent_experiments[-20:]
        if self.db is not None:
            self.db.add_experiment(
                run_id=self.run_id or self.run_dir.name,
                turn=int(exp.id.replace("t", "")) if exp.id.startswith("t") else 0,
                action=exp.action,
                result=exp.result,
                delta=exp.delta,
                node_id=exp.node_id,
            )


def _parse_lesson_blocks(text: str) -> list[tuple[str, str, str | None]]:
    """Extrae bloques '## What <category> - <ts>\\n<content>' de texto de lecciones."""
    import re

    out = []
    for m in re.finditer(
        r"##\s+What\s+([\wáéíóúñü\-]+)\s*-\s*([^\n]+)\n(.*?)(?=\n##|\Z)",
        text, re.S,
    ):
        category, ts, content = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        out.append((category, content, ts))
    if not out:
        # párrafo suelto sin cabecera estructurada
        plain = text.strip()
        if plain:
            out.append(("general", plain, None))
    return out


class ContextManager:
    def __init__(self, threshold_tokens: int = 60000, max_history: int = 8):
        self.threshold = threshold_tokens
        self.max_history = max_history
        self.compacted = False

    def compact(self, history: list, lesson_text: str) -> list:
        """Deja 3 mensajes: estado resumido, resumen de conversación y lessons.md."""
        summary = self._summarize(history)
        state_msg = (
            "ESTADO COMPRIMIDO: la conversación fue demasiado larga. "
            "Resumen de lo acontecido:\n" + summary
        )
        lessons_msg = "MEMORIA PERSISTENTE (lessons.md):\n" + lesson_text
        self.compacted = True
        return [state_msg, lessons_msg]

    def _summarize(self, history: list) -> str:
        lines = []
        for item in history[-20:]:
            if isinstance(item, str):
                lines.append(item)
            elif isinstance(item, dict):
                lines.append(json.dumps(item, ensure_ascii=False)[:400])
        joined = "\n".join(lines)
        return joined[:3000]

    def should_compact(self, text: str, llm) -> bool:
        if self.compacted:
            return False
        try:
            tokens = llm.count_tokens(text)
        except Exception:
            tokens = len(text) // 4
        return tokens > self.threshold