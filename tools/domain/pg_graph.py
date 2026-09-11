"""Procedural Graph de ReaWeb (adaptación de "Procedural Graphs: Self-Evolving
Execution Structures for LLM Agents", Lu et al., Google Research, 2026).

Un Procedural Graph organiza conocimiento PROCEDIMENTAL en triplets dirigidos
atribuidos (u, r, v) con campos de texto (condition, guidance, pitfalls) para
responder "¿qué hacer ahora?" de forma situacional — análogo a cómo un Knowledge
Graph organiza conocimiento factual en (entidad, relación, entidad) para "¿qué es?".

Funcionalidad:
  - Carga y validación del grafo declarativo en domain/generated/pg_graph.yaml.
  - Matching de nodo activo (u_t = Match(a_{t-1}, V)): mapea la última tool call
    del agente al nodo PG correspondiente (tracing en tiempo real).
  - Subgrafo vecindario 2-hop (extracción de la guidance localizada).
  - Generación de guidance situacional a partir del vecindario.
  - Canonicalización de nodos: varias tools pueden converger a un mismo nodo PG
    (dentro del arquetipo knowledge-graph, etc.) — evita multiplicar nodos.

Es conocimiento declarativo en domain/generated/pg_graph.yaml, editable vía
meta-evolución (edit_skill, component=context_memory) o por el PG Proposer
post-run (component=pg_graph), ambos pasando por el acceptance gate.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from config import PATHS

PG_FILE = Path("generated") / "pg_graph.yaml"
DEFAULT_HOPS = 2

# Canonicalización: tools del agente que pueden converger a un nodo PG.
# El matching exacto (paper) falla cuando el solver genera un nombre de acción
# ligeramente distinto al nombre del nodo; esta tabla une alias de runtime a
# nodos del grafo. Los "nodos de capacidad" (no ejecutables directamente) no se
# mapean desde tools.
_TOOL_NODE_ALIASES = {
    "generate_candidate": "generate_candidate",
    "audit_page": "audit_page",
    "audit_visual": "audit_visual",
    "audit_creative": "audit_creative",
    "audit_truth": "audit_truth",
    "select_final": "select_final",
    "revert_workspace": "revert_workspace",
    "review_harness": "review_harness",
    "edit_skill": "edit_skill",
    "fetch_readme": "fetch_readme",
    "fetch_repo_topics": "fetch_repo_topics",
    "git_snapshot": "git_snapshot",
    "seed_workspace": "generate_candidate",
}

RELATION_ORDER = ["LEADS_TO", "TRIGGERS", "PROVIDES_INPUT_FOR", "CONVERGES_TO"]


class ProceduralGraph:
    """Motor del grafo procedural: carga, matching de nodo activo, subgrafo
    localizado y guidance situacional."""

    def __init__(self, path: Path | None = None):
        self.path = path or (PATHS["domain"] / PG_FILE)
        self.data: dict = {}
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.adj_out: dict[str, list[dict]] = {}   # u -> aristas salientes
        self.adj_in: dict[str, list[dict]] = {}    # v -> aristas entrantes
        self.phase_by_node: dict[str, str] = {}
        self.hops = DEFAULT_HOPS
        self.load()

    def load(self) -> None:
        """Carga el YAML; nunca lanza. Grafo vacío si falta o es inválido."""
        self.data = {}
        self.nodes = {}
        self.edges = []
        self.adj_out = {}
        self.adj_in = {}
        self.phase_by_node = {}
        if not self.path.exists():
            return
        try:
            data = yaml.safe_load(self.path.read_text())
        except Exception:
            return
        if not isinstance(data, dict):
            return
        self.data = data
        meta = data.get("meta") or {}
        if isinstance(meta, dict) and "neighborhood_hops" in meta:
            try:
                self.hops = int(meta["neighborhood_hops"])
            except (TypeError, ValueError):
                self.hops = DEFAULT_HOPS
        for n in data.get("nodes") or []:
            if not isinstance(n, dict) or not n.get("id"):
                continue
            nid = n["id"]
            self.nodes[nid] = n
            self.phase_by_node[nid] = n.get("phase", "")
        for e in data.get("edges") or []:
            if not isinstance(e, dict) or not e.get("from") or not e.get("to"):
                continue
            norm = {
                "from": e["from"],
                "to": e["to"],
                "relation": e.get("relation", "LEADS_TO"),
                "condition": e.get("condition", ""),
                "guidance": e.get("guidance", ""),
                "pitfalls": e.get("pitfalls", ""),
            }
            self.edges.append(norm)
            self.adj_out.setdefault(norm["from"], []).append(norm)
            self.adj_in.setdefault(norm["to"], []).append(norm)

    # --- consultas básicas ---
    def is_loaded(self) -> bool:
        return bool(self.nodes)

    def has_node(self, node_id: str) -> bool:
        return node_id in self.nodes

    def node_phase(self, node_id: str) -> str:
        return self.phase_by_node.get(node_id, "")

    def node_label(self, node_id: str) -> str:
        n = self.nodes.get(node_id)
        return n.get("label", node_id) if n else node_id

    def outgoing_edges(self, node_id: str) -> list[dict]:
        return self.adj_out.get(node_id, [])

    def incoming_edges(self, node_id: str) -> list[dict]:
        return self.adj_in.get(node_id, [])

    def all_node_ids(self) -> list[str]:
        return list(self.nodes.keys())

    def phases(self) -> list[str]:
        seen: list[str] = []
        for n in self.nodes.values():
            p = n.get("phase", "")
            if p and p not in seen:
                seen.append(p)
        return seen

    # --- matching de nodo activo (tracing en tiempo real) ---
    def current_node(self, recent_experiments) -> str | None:
        """u_t = Match(a_{t-1}, V): mapea la última acción ejecutada al nodo PG.

        Acepta Experiment objects o dicts con campo 'action'. Si el matching falla
        o no hay acciones, devuelve None (el llamador usará el grafo completo como
        fallback, igual que el paper)."""
        node = None
        for exp in reversed(list(recent_experiments)):
            action = None
            if isinstance(exp, dict):
                action = exp.get("action")
            elif hasattr(exp, "action"):
                action = exp.action
            if not action:
                continue
            canonical = _TOOL_NODE_ALIASES.get(action)
            if canonical and self.has_node(canonical):
                node = canonical
                break
        return node

    # --- subgrafo vecindario (localización) ---
    def neighborhood(self, node_id: str, hops: int | None = None) -> dict:
        """Extrae el vecindario dirigido N_h(u) (nodos alcanzables expandiendo
        hasta `hops` saltos desde el nodo activo, en ambas direcciones).

        Retorna dict con 'nodes' (ids ordenados), 'edges' (aristas del subgrafo)
        y 'relations' (relaciones presentes)."""
        k = hops if hops is not None else self.hops
        if node_id not in self.nodes:
            return self._full_neighborhood()
        reachable: set[str] = {node_id}
        frontier: set[str] = {node_id}
        sub_edges: list[dict] = []
        for _ in range(k):
            nxt: set[str] = set()
            for u in list(frontier):
                for e in self.adj_out.get(u, []):
                    sub_edges.append(e)
                    if e["to"] not in reachable:
                        reachable.add(e["to"])
                        nxt.add(e["to"])
                for e in self.adj_in.get(u, []):
                    sub_edges.append(e)
                    if e["from"] not in reachable:
                        reachable.add(e["from"])
                        nxt.add(e["from"])
            frontier = nxt
        return {
            "nodes": sorted(reachable),
            "edges": sub_edges,
            "relations": sorted({e["relation"] for e in sub_edges}),
        }

    def _full_neighborhood(self) -> dict:
        """Fallback (paper): si el matching falla, se usa el grafo completo."""
        return {
            "nodes": sorted(self.nodes.keys()),
            "edges": list(self.edges),
            "relations": sorted({e["relation"] for e in self.edges}),
        }

    # --- guidance situacional ---
    def guidance(self, node_id: str | None, recent_experiments=None) -> str:
        """Genera guidance situacional del subgrafo localizado.

        Serializa condition/guidance/pitfalls de las aristas del vecindario del
        nodo activo. Si node_id es None o no se encuentra, usa el grafo completo
        como fallback. Cadena vacía si no hay grafo ni aristas."""
        if not self.edges:
            return ""
        active = node_id or self.current_node(recent_experiments)
        sub = self.neighborhood(active) if active and self.has_node(active) \
            else self._full_neighborhood()
        lines: list[str] = []
        for e in sub["edges"]:
            lines.append(f"{e['from']} → {e['to']} ({e['relation']})")
            lines.append(f"  • condición: {e['condition']}")
            lines.append(f"  • guidance: {e['guidance']}")
            if e.get("pitfalls"):
                lines.append(f"  • ⚠ pitfalls: {e['pitfalls']}")
        return "\n".join(lines)

    def guidance_outgoing(self, node_id: str) -> str:
        """Guidance compacta SOLO de las aristas salientes del nodo activo
        (lo que puede hacer a continuación)."""
        edges = self.adj_out.get(node_id, [])
        if not edges:
            return ""
        lines = []
        for e in edges:
            lines.append(f"→ {e['to']} ({e['relation']}): {e['condition']}")
            if e.get("guidance"):
                lines.append(f"    ↳ {e['guidance']}")
            if e.get("pitfalls"):
                lines.append(f"    ⚠ {e['pitfalls']}")
        return "\n".join(lines)

    def state_block(self, recent_experiments) -> str:
        """Bloque para el estado del agente: nodo actual + fases + transiciones
        válidas del vecindario localizado (PG offline guidance)."""
        active = self.current_node(recent_experiments)
        if not self.is_loaded():
            return ""
        if active is None:
            head = "Nodo actual: (sin matching — usando grafo completo como fallback)"
        else:
            head = f"Nodo actual: {active} ({self.node_label(active)}) — fase {self.node_phase(active) or '-'}"
        out = [head]
        if active and self.has_node(active):
            nb = self.neighborhood(active)
            out.append("Camino recorrido: " + self._path_formatted(recent_experiments))
            out.append("Fases del grafo: " + ", ".join(self.phases()))
            out.append("Transiciones válidas (subgrafo %d-hop):" % self.hops)
            lines = self.guidance_outgoing(active)
            out.append(lines if lines else "  (ninguna transición saliente definida)")
        else:
            out.append("Transiciones disponibles (grafo completo):")
            for e in self.edges[:10]:
                out.append(f"- {e['from']} → {e['to']} ({e['relation']})")
        return "\n".join(out)

    def _path_formatted(self, recent_experiments) -> str:
        seen: list[str] = []
        for exp in reversed(list(recent_experiments)):
            action = exp.get("action") if isinstance(exp, dict) else getattr(exp, "action", None)
            canonical = _TOOL_NODE_ALIASES.get(action) if action else None
            if canonical and self.has_node(canonical) and canonical not in seen:
                seen.append(canonical)
                if len(seen) >= 8:
                    break
        seen.reverse()
        return " → ".join(seen) if seen else "(sin pasos aún)"

    def structure_block(self) -> str:
        """Bloque estático del sistema: fases, nodos y reglas de navegación del
        grafo (equivalente al knowledge procedural inyectado una sola vez)."""
        if not self.is_loaded():
            return ""
        out = ["# GRAFO PROCEDIMENTAL (procedural knowledge)", ""]
        for phase in self.phases():
            node_ids = [nid for nid, n in self.nodes.items() if n.get("phase") == phase]
            labels = ", ".join(f"`{nid}` ({self.node_label(nid)})" for nid in node_ids)
            out.append(f"## Fase {phase}:")
            out.append("- " + labels)
        out.append("")
        out.append("Navega el grafo respetando las transiciones: un prerequisito "
                   "ausente invalida la señal y una crítica repetida sin mutación "
                   "intermedia desperdicia turnos. La guidance situacional se "
                   "muestra cada turno en el estado.")
        return "\n".join(out)


_GRAPH = None


def load_graph() -> ProceduralGraph:
    """Instancia única (caché) del grafo procedural."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = ProceduralGraph()
    return _GRAPH


def reset_graph() -> None:
    """Recarga el grafo (útil tras una meta-edición o en tests)."""
    global _GRAPH
    _GRAPH = ProceduralGraph()


def pg_block(executed) -> str:
    """API compatible con skill_graph.deps_block(): bloque dinámico del estado."""
    try:
        return load_graph().state_block(executed)
    except Exception:
        return ""


def pg_structure_block() -> str:
    """Bloque estático del system prompt."""
    try:
        return load_graph().structure_block()
    except Exception:
        return ""


# --- aplicación y validación de propuestas de edición (PG Proposer) ---

VALID_PHASES = {"mutation", "validation", "preparation", "finalization",
                "recovery", "meta_evolution"}
VALID_RELATIONS = {"LEADS_TO", "TRIGGERS", "PROVIDES_INPUT_FOR", "CONVERGES_TO"}


def apply_pg_edits(content: str, edits: dict) -> tuple[str, list[str]]:
    """Aplica una propuesta de edición del PG Proposer sobre el YAML actual.

    edits: {"add_nodes": [...], "delete_nodes": [...], "add_edges": [...],
            "delete_edges": [...]}
    Devuelve (nuevo_yaml, errores). Nunca lanza. Si hay errores, devuelve
    (None, errores) para que el llamador no registre un candidato inválido."""
    try:
        data = yaml.safe_load(content)
    except Exception:
        data = None
    if not isinstance(data, dict):
        return None, ["pg_graph.yaml inválido o ausente: no se puede editar"]
    nodes: dict[str, dict] = {n["id"]: n for n in data.get("nodes") or [] if isinstance(n, dict) and n.get("id")}
    edges: list[dict] = [e for e in data.get("edges") or [] if isinstance(e, dict) and e.get("from") and e.get("to")]
    errors: list[str] = []

    # --- delete_nodes ---
    for nid in edits.get("delete_nodes") or []:
        if not isinstance(nid, str):
            continue
        if nid not in nodes:
            errors.append(f"delete_nodes: nodo '{nid}' no existe")
            continue
        del nodes[nid]
        edges = [e for e in edges if e["from"] != nid and e["to"] != nid]

    # --- add_nodes ---
    for n in edits.get("add_nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        nid = n["id"]
        if nid in nodes:
            errors.append(f"add_nodes: nodo '{nid}' ya existe")
            continue
        phase = n.get("phase", "")
        if phase and phase not in VALID_PHASES:
            errors.append(f"add_nodes: fase inválida '{phase}' para '{nid}'")
            continue
        nodes[nid] = n

    # --- delete_edges ---
    for e in edits.get("delete_edges") or []:
        if not isinstance(e, dict):
            continue
        u, v = e.get("from"), e.get("to")
        before = len(edges)
        edges = [x for x in edges if not (x["from"] == u and x["to"] == v)]
        if len(edges) == before:
            errors.append(f"delete_edges: no existe arista {u} -> {v}")

    # --- add_edges ---
    for e in edits.get("add_edges") or []:
        if not isinstance(e, dict):
            continue
        u, v = e.get("from"), e.get("to")
        if u not in nodes:
            errors.append(f"add_edges: nodo origen '{u}' no existe")
            continue
        if v not in nodes:
            errors.append(f"add_edges: nodo destino '{v}' no existe")
            continue
        rel = e.get("relation", "LEADS_TO")
        if rel not in VALID_RELATIONS:
            errors.append(f"add_edges: relación inválida '{rel}' ({u} -> {v})")
            continue
        edges.append({
            "from": u, "to": v, "relation": rel,
            "condition": e.get("condition", ""),
            "guidance": e.get("guidance", ""),
            "pitfalls": e.get("pitfalls", ""),
        })

    if errors:
        return None, errors

    # --- validación de integridad estructural ---
    if len(nodes) < 2:
        return None, ["grafo resultante con < 2 nodos"]
    if len(nodes) > 30:
        return None, [f"grafo resultante demasiado grande ({len(nodes)} nodos > 30)"]
    node_ids = set(nodes)

    def _has_path_to_terminal(start: str, seen: set[str]) -> bool:
        if start in seen:
            return False
        seen = seen | {start}
        outs = [(e["from"], e["to"]) for e in edges if e["from"] == start]
        if not outs:
            return True  # nodo terminal (sin salientes)
        return any(e[1] in node_ids and _has_path_to_terminal(e[1], seen) for e in outs)

    for nid in node_ids:
        if not _has_path_to_terminal(nid, set()):
            errors.append(f"nodo '{nid}' no tiene ruta dirigida a un nodo terminal")
            break

    if errors:
        return None, errors

    ordered = list(data.keys())
    if "meta" not in ordered:
        ordered.insert(0, "meta")
    new_data: dict = {}
    if "meta" in data:
        new_data["meta"] = data["meta"]
    new_data["nodes"] = [nodes[nid] for nid in sorted(nodes)]
    new_data["edges"] = edges
    try:
        out = yaml.safe_dump(new_data, sort_keys=False, allow_unicode=True,
                             default_flow_style=False)
    except Exception as exc:
        return None, [f"error serializando YAML: {exc}"]
    return out, []