"""Bucle principal del agente ReASearch: re-emisión de estado, tool-calling,
memoria, presupuesto y compactación de contexto."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import jinja2

from agent.budget_tracker import BudgetTracker
from agent.llm import LLMResponse
from agent.memory_db import MemoryDB
from agent.state import ContextManager, Experiment, Memory, SearchTree, TreeNode
from agent import harness_snapshot
from config import CONTEXT_DEFAULTS, ensure_dirs, LESSON_AUTO, PATHS


class Agent:
    def __init__(
        self,
        llm,
        archetype_name: str,
        task: str,
        rules: str = "",
        stack: str = "",
        run_dir: Path | None = None,
        max_turns: int = 20,
        max_cost_usd: float = 5.0,
        allow_meta_edits: bool = True,
        verbose: bool = True,
        target_h: int = 0,
        initial_url: str = "",
        quick: bool = False,
    ):
        self.llm = llm
        self.archetype_name = archetype_name
        self.task = task
        self.rules = rules
        self.stack = stack
        self.allow_meta_edits = allow_meta_edits
        self.verbose = verbose
        self.initial_url = initial_url
        self.quick = quick

        run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "--" + archetype_name
        self.run_dir = run_dir or (PATHS["runs"] / run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = self.run_dir.name

        self.budget = BudgetTracker(max_turns=max_turns, max_cost_usd=max_cost_usd)
        self.db = MemoryDB()
        self.memory = Memory(run_dir=self.run_dir, db=self.db, run_id=self.run_id)
        self._auto_lesson_keys: set[tuple] = set()
        self._auto_lesson_count = 0
        self._content_lesson_count = 0
        self._last_functional_tests = None
        self.tree = SearchTree(
            path=self.run_dir / "search_tree.json", run_id=self.run_id, db=self.db
        )
        self.harness_start = harness_snapshot.snapshot()
        self.task_hash = harness_snapshot.task_hash(task)
        self.db.upsert_run(
            run_id=self.run_id,
            archetype=archetype_name,
            task=task,
            task_hash=self.task_hash,
            model=getattr(llm, "model", "?"),
            max_turns=max_turns,
            started=datetime.now().isoformat(),
            status="running",
            initial_url=initial_url,
            harness_hash=self.harness_start["tree_hash"],
        )
        self.context = ContextManager(
            threshold_tokens=CONTEXT_DEFAULTS["compaction_threshold_tokens"],
            max_history=CONTEXT_DEFAULTS["max_history_turns"],
        )
        self.history: list = []
        self.turn = 0
        self._no_tool_streak = 0
        self.last_transcript: list = []
        self.target_h = target_h
        self.hypothesis_count = 0

        # Procedural Graph (PG): nodo activo estimado de la última tool call,
        # camino recorrido en el grafo y json de la run config.
        # Leído de env en tiempo de run (no de la constante congelada de config)
        # para que el driver de baterías pueda alternar on/off por proceso.
        self.pg_enabled = os.environ.get("PG_GRAPH_ENABLED", "1") != "0"
        self.pg_node = None
        self.pg_phase = None
        self.pg_path: list[str] = []
        try:
            from tools.domain.pg_graph import load_graph
            self.pg_graph = load_graph() if self.pg_enabled else None
        except Exception:
            self.pg_graph = None

        # registrar run en transcript
        (self.run_dir / "run_config.json").write_text(
            json.dumps(
                {
                    "archetype": archetype_name,
                    "task": task,
                    "task_hash": self.task_hash,
                    "model": getattr(llm, "model", "?"),
                    "max_turns": max_turns,
                    "started": datetime.now().isoformat(),
                    "initial_url": initial_url,
                    "flags": {"pg_enabled": self.pg_enabled},
                    "harness": {
                        "start": self.harness_start["tree_hash"],
                        "n_files": self.harness_start["n_files"],
                        "files": self.harness_start["files"],
                    },
                },
                indent=2,
            )
        )

    # --- registro en transcript ---
    def _log(self, kind: str, payload: dict) -> None:
        entry = {"turn": self.turn, "kind": kind, "ts": datetime.now().isoformat(), **payload}
        with (self.run_dir / "transcript.jsonl").open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.last_transcript.append(entry)

    # --- render del prompt ---
    def _system_prompt(self) -> str:
        base = (PATHS["prompts"] / "system_base.txt").read_text()
        base = base.replace("{archetype}", self.archetype_name)
        meta_note = ""
        if not self.allow_meta_edits:
            meta_note = "\nNOTA: la meta-evolución (edit_skill/review_harness) está deshabilitada en esta run."
        if self.quick:
            meta_note += (
                "\nNOTA MODO RÁPIDO: sin críticos VLM (audit_visual/audit_creative/audit_truth). "
                "Prioriza cumplir las secciones obligatorias y el test funcional; "
                "selecciona el final lo antes posible sin iteraciones estéticas."
            )
        target_note = ""
        if self.target_h:
            target_note = (
                "\nOBJETIVO DE RUN (target-h="
                + str(self.target_h)
                + "): debes generar y auditar al menos las hipótesis H0..H"
                + str(self.target_h)
                + " ("
                + str(self.target_h + 1)
                + " candidatos) ANTES de seleccionar el final. No declares fin hasta alcanzarlo, salvo que se agote el presupuesto."
            )
        rules_block = ""
        if self.rules:
            rules_block = "\n\n# REGLAS Y STACK DEL ARQUETIPO (contexto precargado)\n" + self.rules[:4000]
        skills_block = self._active_skills_prompt()
        pg_block = ""
        if self.pg_enabled and self.pg_graph is not None:
            try:
                from tools.domain.pg_graph import pg_structure_block
                pg_block = pg_structure_block()
            except Exception:
                pg_block = ""
        return base + meta_note + target_note + rules_block + skills_block + pg_block

    def _active_skills_prompt(self) -> str:
        """WikiSkill §3.2.1 (full injection) + PEARL/PG: inyecta los SKILL.md
        activos (aceptados por el gate, presentes en domain/skills/), RE-RANKEADOS
        por relevancia semántica (LPRA, PG_RERANK_ENABLED) y con separación
        core/contextual (SCL): los skills core (>= PG_CORE_CONVERGENT_COUNT usos
        convergentes) siempre van; los contextuales se recortan al pool top-K."""
        try:
            if not self._wiki_enabled():
                return ""
            sk_root = PATHS["skills"]
            if not sk_root.exists():
                return ""
            blocks = []
            for d in sorted(sk_root.iterdir()):
                sk = d / "SKILL.md"
                if d.is_dir() and sk.exists():
                    blocks.append(f"## SKILL {d.name}\n{sk.read_text(errors='replace')[:4000]}")
            if not blocks:
                return ""

            from tools.domain.pg_reranker import parse_skill_name, rerank_skills
            from config import PG_CORE_CONVERGENT_COUNT, PG_RERANK_ENABLED, \
                PG_RERANK_MIN_SCORE, PG_RERANK_TOP_K

            # Fase 6 (SCL): dividir core vs contextuales por uso convergente
            core_names = set()
            try:
                from agent.memory_db import MemoryDB
                db = MemoryDB()
                try:
                    counts = db.usage_counts_by_skill(min_count=PG_CORE_CONVERGENT_COUNT)
                    core_names = set(counts.keys())
                finally:
                    db.close()
            except Exception:
                core_names = set()
            core = [b for b in blocks if parse_skill_name(b) in core_names]
            contextual = [b for b in blocks if b not in core]

            # Fase 5 (LPRA): re-rankear el grupo contextual (no toca el core)
            try:
                if PG_RERANK_ENABLED and contextual:
                    pg_ctx = f"nodo={self.pg_node or '-'}, fase={self.pg_phase or '-'}"
                    contextual = rerank_skills(
                        contextual, self.llm, task=self.task, pg_context=pg_ctx,
                        top_k=PG_RERANK_TOP_K, min_score=PG_RERANK_MIN_SCORE,
                    )
                else:
                    contextual = contextual[:PG_RERANK_TOP_K]
            except Exception:
                contextual = contextual[:PG_RERANK_TOP_K]

            blocks = core + contextual
            if not blocks:
                return ""
            out = []
            if len(core) > 0:
                out.append("## SKILLS CORE (siempre presentes — uso convergente)")
                out.extend(core)
            if len(contextual) > 0:
                out.append("\n## SKILLS CONTEXTUALES (seleccionados para esta tarea — LPRA)")
                out.extend(contextual)
            return "\n".join(out)
        except Exception:
            return ""

    def _track_pg(self) -> None:
        """Matching de nodo activo del Procedural Graph (u_t = Match(a_{t-1}, V)):
        mapea las últimas acciones ejecutadas al nodo PG y actualiza el camino
        recorrido. No bloqueante; nunca lanza."""
        if not self.pg_enabled or self.pg_graph is None:
            return
        try:
            node = self.pg_graph.current_node(self.memory.recent_experiments)
            self.pg_node = node
            self.pg_phase = self.pg_graph.node_phase(node) if node else None
            if node and (not self.pg_path or self.pg_path[-1] != node):
                self.pg_path.append(node)
                self.pg_path = self.pg_path[-20:]
        except Exception:
            pass

    def _snapshot(self, node_id: str) -> str:
        """Congela workspace/current en runs/<run_id>/candidates/<node_id>/."""
        import shutil

        src = PATHS["current"]
        if not (src / "index.html").exists():
            self._log("system", {"event": "snapshot_skipped", "node": node_id, "reason": "sin index.html"})
            return "(sin snapshot)"
        dst = self.run_dir / "candidates" / node_id
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dst / f.name)
            elif f.is_dir():
                shutil.copytree(f, dst / f.name)
        self._log("system", {"event": "snapshot", "node": node_id, "to": str(dst)})
        return str(dst)

    def _snapshot_workspace(self) -> dict[str, int]:
        """Punto 12c: captura tamaños de archivos del workspace antes de una mutación
        para generar un resumen de diff en las lecciones automáticas."""
        import hashlib
        snap: dict[str, int] = {}
        target = PATHS["current"]
        if not target.exists():
            return snap
        for f in target.iterdir():
            if f.is_file():
                try:
                    data = f.read_bytes()
                    snap[f.name] = len(data)
                except Exception:
                    pass
        return snap

    def _workspace_diff_summary(self, pre: dict[str, int]) -> str:
        """Punto 12c: compara estado del workspace post-mutación contra el
        snapshot previo y devuelve un resumen tipo: +index.html(+1200b), -styles.css(-300b)"""
        import hashlib
        post: dict[str, int] = {}
        target = PATHS["current"]
        if not target.exists():
            return ""
        for f in target.iterdir():
            if f.is_file():
                try:
                    post[f.name] = len(f.read_bytes())
                except Exception:
                    pass
        changes: list[str] = []
        all_files = set(pre.keys()) | set(post.keys())
        for fname in sorted(all_files):
            old = pre.get(fname)
            new = post.get(fname)
            if old is None:
                changes.append(f"+{fname}(+{new}b)")
            elif new is None:
                changes.append(f"-{fname}(-{old}b)")
            elif new != old:
                delta = new - old
                changes.append(f"~{fname}({delta:+d}b)")
        return ", ".join(changes[:6]) if changes else "sin cambios"

    def _stash_vlm(self, blk: dict | None, issues_key: str, sug_key: str) -> None:
        """Guarda el último feedback VLM estructurado (issues/suggestions) para
        inyectarlo en el estado como objetivo de la siguiente mutación."""
        if not isinstance(blk, dict):
            return
        issues = blk.get(issues_key)
        sugs = blk.get(sug_key)
        if isinstance(issues, list) or isinstance(sugs, list):
            self.last_vlm = {
                "issues": [str(x)[:200] for x in (issues or [])][:4],
                "suggestions": [str(x)[:300] for x in (sugs or [])][:4],
            }

    def _render_state(self, stagnation: str | None) -> str:
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PATHS["prompts"])))
        tmpl = env.get_template("state_template.j2")
        best = self.tree.best()
        best_fields = {
            "id": best.id if best else "-",
            "metrics_summary": (
                ", ".join(
                    f"{k}={v}" for k, v in sorted(best.metrics.items())
                    if k not in ("total", "fails")
                )
                + f" | total={best.metrics.get('total','-')}"
                if best
                else "-"
            ),
            "path": "-",
        }
        # Desglose de secciones obligatorias del mejor candidato (si existe)
        if best:
            cand_dir = self.run_dir / "candidates" / best.id
            from tools.domain.evaluator import extract_sections, _html_has_section
            sections = extract_sections(self.task)
            html_path = cand_dir / "index.html"
            if sections and html_path.exists():
                h = html_path.read_text(errors="replace")
                fails = [s for s in sections if not _html_has_section(h, s)]
                best_fields["sections"] = sections
                best_fields["sections_fails"] = fails
                best_fields["sections_present"] = len(sections) - len(fails)
                best_fields["sections_total"] = len(sections)
        # CHECKLIST DE SUBTAREAS (loop F1): estado ok/fail por subtarea del mejor
        best_fields["subtasks"] = self._subtask_checklist(best.id if best else None)
        best_fields["novelty"] = best.metrics.get("novelty") if best else None
        # F2: fallos del evaluador + último feedback VLM del mejor candidato,
        # como objetivos explícitos de la siguiente mutación
        best_fields["fails"] = best.metrics.get("fails") if best else None
        # F2: repos huérfanos — lista explícita para el template
        best_fields["parts_fails"] = []
        if best:
            cand_dir = self.run_dir / "candidates" / best.id
            repos_dir = cand_dir / "repos"
            if repos_dir.is_dir():
                import re as _re
                h = (cand_dir / "index.html").read_text(errors="replace") if (cand_dir / "index.html").exists() else ""
                linked = set(_re.findall(r'href=["\']([^"\']*repos/[^"\']*index\.html)["\']', h))
                orphan = [p.name for p in repos_dir.iterdir()
                          if p.is_dir() and (p / "index.html").exists()
                          and f"repos/{p.name}/index.html" not in linked]
                if orphan:
                    best_fields["parts_fails"] = [
                        f"REPOS HUÉRFANOS: {', '.join(orphan)} — añade <a href=\"repos/{r}/index.html\"> para cada uno en index.html"
                        for r in orphan[:6]
                    ]
        # Punto 12 (Who&When): causa dominante del peor eje del mejor candidato
        best_fields["root_cause"] = best.metrics.get("root_cause") if best else None
        vlm = getattr(self, "last_vlm", None) or {}
        best_fields["vlm_issues"] = vlm.get("issues") or []
        best_fields["vlm_suggestions"] = vlm.get("suggestions") or []
        recent = []
        for exp in self.memory.recent_experiments[-8:]:
            recent.append(
                {
                    "id": exp.id,
                    "action": exp.action,
                    "result": exp.result,
                    "delta": exp.delta,
                }
            )
        # Punto 12 (grafo de dependencias): advertencias de aristas violadas
        try:
            from tools.domain.skill_graph import deps_block
            skill_deps = deps_block([e.action for e in self.memory.recent_experiments])
        except Exception:
            skill_deps = ""
        # Procedural Graph: guidance situacional del nodo activo
        pg_state = ""
        if self.pg_enabled and self.pg_graph is not None:
            try:
                self._track_pg()
                pg_state = self.pg_graph.state_block(self.memory.recent_experiments)
            except Exception:
                pg_state = ""
        return tmpl.render(
            turn_number=self.turn,
            archetype_name=self.archetype_name,
            task=self.task,
            initial_url=self.initial_url,
            seeded=getattr(self, "seeded", False),
            turns_remaining=self.budget.turns_remaining(),
            turns_total=self.budget.max_turns,
            cost_so_far=self.budget.cost_so_far,
            best=best_fields,
            recent=recent,
            tree=self.tree.summary(max_nodes=CONTEXT_DEFAULTS["search_tree_max_nodes"]),
            lessons=self.memory.read_global_lessons()[:3000],
            skill_deps=skill_deps,
            pg_state=pg_state,
            stagnation=stagnation,
            last_action_summary=self._last_action_summary(),
            target_h=self.target_h,
            hypotheses_done=self.hypothesis_count,
        )

    def _last_action_summary(self) -> str:
        for entry in reversed(self.last_transcript):
            if entry["kind"] in ("tool", "eval"):
                return f"{entry.get('tool','')}: {str(entry.get('result',''))[:400]}"
        return "-"

    # --- ejecución de tools ---
    def _subtask_checklist(self, candidate_id: str | None) -> list[dict]:
        """Estado ok/fail de cada subtarea del plan (loop F1) para un candidato.

        Usa el snapshot congelado del candidato (runs/.../candidates/<id>/), que
        es estable entre turnos. Los tests funcionales vienen del último evaluate()
        guardado en las métricas del nodo (sin re-ejecutar Chrome por turno)."""
        from tools.domain.evaluator import subtasks_status, extract_subtasks
        if candidate_id is None:
            return []
        cand_dir = self.run_dir / "candidates" / candidate_id
        if not (cand_dir / "index.html").exists():
            return []
        h = (cand_dir / "index.html").read_text(errors="replace")
        css = " ".join(p.read_text(errors="replace") for p in cand_dir.glob("*.css"))
        js = " ".join(p.read_text(errors="replace") for p in cand_dir.glob("*.js"))
        node = self.tree.nodes.get(candidate_id)
        func_tests = node.metrics.get("functional_tests") if node else None
        if not func_tests:
            func_tests = self._last_functional_tests
        status = subtasks_status(h, css, js, self.task, func_tests)
        cheques = {st["id"]: st["cheque"] for st in extract_subtasks(self.task)}
        return [
            {
                "id": sid,
                "tipo": s["tipo"],
                "ok": s["ok"],
                "detail": s["detail"],
                "cheque": cheques.get(sid, ""),
            }
            for sid, s in sorted(status.items())
        ]

    def _safe_history_slice(self) -> list:
        """Devuelve un slice del historial que empieza SIEMPRE en un mensaje de
        texto (user/model), nunca en un function_response/call suelto. La API de
        Gemini exige que un function_response preceda inmediatamente a un
        function_call, y que esos pares estén precedidos por texto normal."""
        n = self.context.max_history * 2
        start = max(0, len(self.history) - n)
        while start < len(self.history):
            parts = self.history[start].get("parts", [])
            if parts and ("text" in parts[0]):
                break
            start += 1
        return self.history[start:]

    def _exec_tool(self, registry, call) -> tuple[str, dict]:
        tool = registry.get(call.name)
        # Meta-editor solo si está permitido
        if call.name in ("edit_skill", "review_harness") and not self.allow_meta_edits:
            msg = "ERROR: meta-evolución deshabilitada."
            self._log("tool", {"tool": call.name, "args": call.args, "result": msg})
            return msg, {}
        try:
            kwargs = dict(call.args)
            kwargs["run_id"] = self.run_id
            if call.name == "inspect_archetype" and not kwargs.get("archetype"):
                kwargs["archetype"] = self.archetype_name
            # --- Gate estricto A2: select_final requiere checklist 100% ok ----
            if call.name == "select_final":
                best = self.tree.best()
                if best:
                    fails = [s["id"] for s in self._subtask_checklist(best.id)
                             if not s.get("ok")]
                    if fails:
                        msg = (
                            f"ERROR: select_final bloqueado — subtareas en FAIL: "
                            f"{fails}. Resuélvelas primero con generate_candidate."
                        )
                        self._log("tool", {
                            "tool": call.name, "args": call.args,
                            "result": msg[:500],
                        })
                        return msg, {}
            # --- fin gate select_final ----------------------------------------
            # --- Temperatura B: escalera por fase (fase creativa post-H0) -----
            if call.name == "generate_candidate":
                from config import GENERATOR_CREATIVE_TEMP
                best_n = self.tree.best()
                cl_ok = True
                if best_n and best_n.id:
                    cl = self._subtask_checklist(best_n.id)
                    cl_ok = (len(cl) > 0 and not any(not s.get("ok") for s in cl))
                temp = (GENERATOR_CREATIVE_TEMP
                        if cl_ok and self.hypothesis_count >= 1 else 0.7)
                kwargs["temperature"] = temp
            # --- fin temperatura ----------------------------------------------
            result = tool.run(**kwargs)
        except Exception as e:
            result = f"ERROR ejecutando {call.name}: {e}"
        # Guardar los tests funcionales si la tool los expone (loop F1): permite
        # al checklist de subtareas marcar ok/fail funcional sin re-ejecutar Chrome.
        if hasattr(tool, "last_functional_tests") and tool.last_functional_tests:
            self._last_functional_tests = tool.last_functional_tests
        self._log("tool", {"tool": call.name, "args": call.args, "result": result[:2000]})
        return result, {}

    def _handle_tool_call(self, registry, call) -> None:
        """Ejecuta una tool con TODA la semántica posterior del loop (snapshot,
        memoria de experimentos, tracking PG, audits automáticos, lessons).
        Compartida entre las tool_calls del modelo y el auto-unblock por stall
        del harness (garantiza progreso si el agente se bloquea repitiendo)."""
        prev_best = self._current_best_score()
        pre_snapshot = self._snapshot_workspace() if call.name == "generate_candidate" else None
        result, _ = self._exec_tool(registry, call)
        self.history.append({"role": "model", "parts": [{"function_call": {"name": call.name, "args": call.args}}]})
        self.history.append({"role": "user", "parts": [{"function_response": {"name": call.name, "response": {"result": result}}}]})
        node_id = self._handle_eval_result(call, result)
        node_total = (
            float(self.tree.nodes[node_id].metrics.get("total", 0.0))
            if node_id and node_id in self.tree.nodes else 0.0
        )
        delta = node_total - prev_best
        pg_node = pg_phase = None
        if self.pg_enabled and self.pg_graph is not None:
            try:
                from tools.domain.pg_graph import _TOOL_NODE_ALIASES
                cn = _TOOL_NODE_ALIASES.get(call.name)
                if cn and self.pg_graph.has_node(cn):
                    pg_node = cn
                    pg_phase = self.pg_graph.node_phase(cn)
            except Exception:
                pass
        self.memory.add_experiment(
            Experiment(
                id=f"t{self.turn}",
                action=call.name,
                result=result[:200],
                delta=f"{delta:+.1f}",
                node_id=node_id,
                pg_node=pg_node,
                pg_phase=pg_phase,
            )
        )
        self._track_pg()
        self._log("pg", {"tool": call.name, "pg_node": self.pg_node,
                         "pg_phase": self.pg_phase,
                         "pg_path": list(self.pg_path)})
        if call.name == "generate_candidate" and node_id is not None:
            self._snapshot(node_id)
            self._auto_truth_audit(registry, node_id)
            self._auto_visual_audit(registry, node_id)
        if call.name == "generate_candidate" and node_id is not None:
            self._compute_novelty(node_id)
        file_diff = ""
        if call.name == "generate_candidate" and pre_snapshot is not None:
            file_diff = self._workspace_diff_summary(pre_snapshot)
        self._maybe_auto_lesson(call, delta, node_id, result, file_diff=file_diff)
        if node_id is not None and call.name in ("generate_candidate", "audit_page"):
            self._maybe_subtask_lesson(node_id)

    def _auto_unblock(self, registry) -> None:
        """Escalada estricta: si el agente lleva N turnos sin tool_call (stall,
        p.ej. repite un meta JSON inválido), el harness toma el control y ejecuta
        una mutación útil (reparar subtareas pendientes o refinar estética).
        Es la versión EJECUTABLE de 'si algo no está bien, se repite'."""
        from types import SimpleNamespace
        best = self.tree.best()
        missing: list[str] = []
        if best and best.id:
            missing = [s["id"] for s in self._subtask_checklist(best.id) if not s.get("ok")]
        if missing:
            obj = (
                "Repara de inmediato las subtareas pendientes (estructural/funcional): "
                + ", ".join(missing)
                + ". Conserva lo que ya funciona y completa TODAS las secciones del checklist."
            )
            ev = {"event": "auto_unblock", "missing": missing}
        else:
            obj = (
                "El mejor candidato ya está completo. Refina la ESTÉTICA y las "
                "micro-interacciones (tipografía display, jerarquía, hover, dark-mode), "
                "manteniendo todas las funciones y secciones."
            )
            ev = {"event": "auto_unblock", "missing": []}
        self._log("system", dict(ev, objective=obj[:160]))
        call = SimpleNamespace(name="generate_candidate", args={"objective": obj})
        try:
            self._handle_tool_call(registry, call)
        except Exception as e:
            self._log("system", {"event": "auto_unblock", "error": str(e)[:200]})

    def _handle_eval_result(self, call, result: str) -> str | None:
        """Interpreta métricas de generate_candidate, audit_page o audit_visual y
        actualiza el árbol de búsqueda en términos de hipótesis H0..Hn.

        - generate_candidate: crea una NUEVA hipótesis H<i> (baseline H0 la primera).
        - audit_page: CONFIRMA (doble verificación) la hipótesis actual, actualizando
          sus métricas sin crear nodos duplicados.
        - audit_visual: crítica VLM estética. Añade el axis `vlm` (0-100) al nodo
          actual SIN crear hipótesis ni tocar el total (es feedback de diseño).
        """
        import re

        # audit_truth: juicio de verdad basado en datasets. Añade los axes
        # `truth` (diseño VLM vs referencias reales) y `parts_ok` (partes
        # integrantes conectadas) al nodo actual. Si hay design_score, recombina
        # el total igual que audit_visual (max del proxy visual estático).
        if call.name == "audit_truth":
            from tools.domain.evaluator import parse_metrics_block
            _blk = parse_metrics_block(result)
            design_score = None
            if _blk is not None:
                design_score = _blk.get("diseño_vlm")
                if isinstance(design_score, str) and design_score.lstrip("-").isdigit():
                    design_score = int(design_score)
                if not isinstance(design_score, (int, float)):
                    design_score = None
                parts_ok = bool(_blk.get("parts_ok", "partes=ok" in result))
            else:
                m = re.search(r"diseño_vlm=(\d+)", result)
                design_score = int(m.group(1)) if m else None
                parts_ok = "partes=ok" in result
            node_id = f"H{self.hypothesis_count - 1}" if self.hypothesis_count else None
            blended = None
            if node_id and node_id in self.tree.nodes:
                existing = self.tree.nodes[node_id]
                if design_score is not None:
                    existing.metrics["truth"] = design_score
                    from tools.domain.evaluator import blend_visual_total
                    blended = blend_visual_total(existing.metrics, design_score)
                    if blended is not None:
                        existing.metrics["total"] = blended
                        existing.metrics["visual"] = max(
                            existing.metrics.get("visual") or 0, design_score)
                if parts_ok:
                    existing.metrics["parts_ok"] = 100
                else:
                    existing.metrics["parts_ok"] = 0
                existing.description = result[:200]
                self.tree.add(existing)
            self._log("eval", {"candidate": node_id, "tool": "audit_truth",
                               "truth": design_score, "total": blended,
                               "parts_ok": parts_ok, "version": "truth"})
            return node_id

        # audit_visual: feedback estético VLM. Recombina el total del nodo
        # sustituyendo el proxy visual estático por la mejor señal (max).
        if call.name == "audit_visual":
            from tools.domain.evaluator import parse_metrics_block
            _blk = parse_metrics_block(result)
            if _blk is not None and isinstance(_blk.get("visual_vlm"), (int, float)):
                vlm = int(_blk["visual_vlm"])
            else:
                m = re.search(r"visual_vlm=(\d+)", result)
                if not m:
                    return None
                vlm = int(m.group(1))
            self._stash_vlm(_blk, "vlm_issues", "vlm_suggestions")
            node_id = f"H{self.hypothesis_count - 1}" if self.hypothesis_count else None
            blended = None
            if node_id and node_id in self.tree.nodes:
                existing = self.tree.nodes[node_id]
                existing.metrics["vlm"] = vlm
                from tools.domain.evaluator import blend_visual_total
                blended = blend_visual_total(existing.metrics, vlm)
                if blended is not None:
                    existing.metrics["total"] = blended
                    existing.metrics["visual"] = max(
                        existing.metrics.get("visual") or 0, vlm)
                existing.description = result[:200]
                self.tree.add(existing)  # persiste en JSON y en DB (upsert_node)
            self._log("eval", {"candidate": node_id, "tool": "audit_visual",
                               "vlm": vlm, "total": blended,
                               "version": "visual"})
            return node_id

        # audit_creative: señal VLM de CREATIVIDAD (diseño de vanguardia, lo
        # visible en el screenshot, no strings). Añade el axis `creativity`
        # (0-100) al nodo actual y recombina el total igual que audit_visual.
        if call.name == "audit_creative":
            from tools.domain.evaluator import parse_metrics_block
            _blk = parse_metrics_block(result)
            if _blk is not None and isinstance(_blk.get("creativity_vlm"), (int, float)):
                cr = int(_blk["creativity_vlm"])
            else:
                m = re.search(r"creativity_vlm=(\d+)", result)
                if not m:
                    return None
                cr = int(m.group(1))
            self._stash_vlm(_blk, "creativity_issues", "creativity_suggestions")
            node_id = f"H{self.hypothesis_count - 1}" if self.hypothesis_count else None
            blended = None
            if node_id and node_id in self.tree.nodes:
                existing = self.tree.nodes[node_id]
                existing.metrics["creativity"] = cr
                from tools.domain.evaluator import blend_visual_total
                vlm_prev = existing.metrics.get("vlm")
                blended = blend_visual_total(existing.metrics, vlm_prev)
                if blended is not None:
                    existing.metrics["total"] = blended
                existing.description = result[:200]
                self.tree.add(existing)
            self._log("eval", {"candidate": node_id, "tool": "audit_creative",
                               "creativity": cr, "total": blended,
                               "version": "creative"})
            return node_id

        if call.name not in ("generate_candidate", "audit_page"):
            return None

        # Salida estructurada (bloque JSON canónico) primero; regex como fallback
        # retrocompatible con runs históricas (Kimi K.3: "stringly-typed").
        from tools.domain.evaluator import parse_metrics_block
        _blk = parse_metrics_block(result)
        if _blk is not None:
            total = _blk.get("total")
            if not isinstance(total, (int, float)):
                return None
            total = int(total)
            metrics = {
                k: int(v) for k, v in _blk.items()
                if k in ("seo", "a11y", "performance", "responsive",
                        "best_practices", "visual", "task", "structure",
                        "functional", "creativity")
                and isinstance(v, (int, float))
            }
            metrics["total"] = total
            if isinstance(_blk.get("fails"), list) and _blk["fails"]:
                metrics["fails"] = [str(x)[:160] for x in _blk["fails"][:8]]
            # Punto 12 (Who&When): atribuir la causa dominante si hay síntomas
            from tools.domain.evaluator import detect_root_cause
            cause, _detail = detect_root_cause(metrics)
            if cause:
                metrics["root_cause"] = cause
        else:
            m = re.search(r"total=(\d+)", result)
            if not m:
                return None
            total = int(m.group(1))
            metrics: dict = {}
            mapping = {
                r"\bseo=(\d+)": "seo",
                r"\ba11y=(\d+)": "a11y",
                r"\bperf=(\d+)": "performance",
                r"\bresp=(\d+)": "responsive",
                r"\bbp=(\d+)": "best_practices",
                r"\bvisual=(\d+)": "visual",
                r"\btask=(\d+)": "task",
                r"\bstructure=(\d+)": "structure",
                r"\bfunctional=(\d+)": "functional",
                r"\bcreativity=(\d+)": "creativity",
            }
            for token, key in mapping.items():
                m2 = re.search(token, result)
                if m2:
                    metrics[key] = int(m2.group(1))
            metrics["total"] = total
            from tools.domain.evaluator import detect_root_cause
            cause, _detail = detect_root_cause(metrics)
            if cause:
                metrics["root_cause"] = cause

        prev_best = self.tree.best()
        prev_score = prev_best.metrics.get("total", -1) if prev_best else -1

        is_confirm = False
        if call.name == "generate_candidate":
            node_id = f"H{self.hypothesis_count}"
            self.hypothesis_count += 1
            self._log("eval", {"candidate": node_id, "tool": "generate_candidate", "total": total, "task": metrics.get("task"), "version": "new"})
        else:
            # audit_page confirma la hipótesis más reciente
            node_id = f"H{self.hypothesis_count - 1}"
            if self.hypothesis_count == 0 or node_id not in self.tree.nodes:
                node_id = f"H{self.hypothesis_count}"
                self.hypothesis_count += 1
                self._log("eval", {"candidate": node_id, "tool": "audit_page", "total": total, "task": metrics.get("task"), "version": "inferred"})
            else:
                is_confirm = True
                self._log("eval", {"candidate": node_id, "tool": "audit_page", "total": total, "task": metrics.get("task"), "version": "confirm"})

        # Parent coherente: al confirmar se respeta el parent del nodo existente
        existing = self.tree.nodes.get(node_id)
        if existing is not None:
            parent = existing.parent
            already_best = existing.status == "best_branch"
            status = "best_branch" if (total >= prev_score or already_best) else existing.status
        else:
            parent = prev_best.id if prev_best else None
            status = "best_branch" if total >= prev_score else "explored"
        if is_confirm:
            status = "best_branch" if total >= prev_score else "explored"

        self.tree.add(
            TreeNode(
                id=node_id,
                parent=parent,
                action=call.name,
                metrics=metrics,
                status=status,
                description=result[:200],
            )
        )
        return node_id

    def _maybe_subtask_lesson(self, node_id: str | None) -> None:
        """Lección por RESOLUCIÓN DE SUBTAREA (loop F1): cuando un candidato nuevo
        pasa una subtarea que el mejor previo tenía en FAIL, se registra una
        lección 'worked' con el cheque y su detalle (qué se arregló). A diferencia
        de la lección por delta global, esta ata la lección al cheque concreto."""
        if not node_id or self._content_lesson_count >= LESSON_AUTO["max_per_run"]:
            return
        node = self.tree.nodes.get(node_id)
        if node is None:
            return
        checklist = self._subtask_checklist(node_id)
        if not checklist:
            return
        prev_best = self.tree.best()
        prev_check = self._subtask_checklist(prev_best.id) if prev_best and prev_best.id != node_id else []
        prev_map = {c["id"]: c for c in prev_check}
        for c in checklist:
            prev = prev_map.get(c["id"])
            if prev and not prev["ok"] and c["ok"]:
                key = ("worked", f"subtask:{c['id']}", c["cheque"][:80])
                if key in self._auto_lesson_keys:
                    continue
                self._auto_lesson_keys.add(key)
                self._content_lesson_count += 1
                content = (
                    f"[auto:subtask] RESUELTA en {node_id}: {c['id']} — {c['cheque']}"
                )
                text = f"## What worked - {datetime.now().isoformat(timespec='seconds')}\n{content}"
                self.memory.append_incremental(text)
                self._log("system", {"event": "auto_lesson", "category": "worked",
                                     "tool": "subtask", "subtask": c["id"],
                                     "node": node_id, "por": "resolucion"})

    def _maybe_auto_lesson(self, call, delta: float, node_id: str | None,
                           result: str, file_diff: str = "") -> None:
        """Refuerzo automático de aprendizaje: si una tool de optimización produce
        una mejora o regresión >= umbral (LESSON_AUTO), registra una lección
        worked/didnt deduplicada en la run, sin depender de que el LLM llame a
        update_lessons. Es el criterio objetivo que materializa EVOLUTION.md.

        Las tools de DIAGNÓSTICO VLM (audit_creative/audit_truth/audit_visual)
        no se categorizan por el delta del total: su puntuación BAJA es
        información (miden algo que era bajo), no una regresión de la tool. Si se
        registrara como 'didnt', el harness "aprendería" que llamar a audit_creative
        es malo (lección anti-señal). Para ellas la lección sale del CONTENIDO:
        score bajo -> 'didnt' con el cheque concreto y su sugerencia; score alto
        -> 'worked'."""
        if call.name not in ("generate_candidate", "audit_page", "audit_visual", "audit_truth", "audit_creative"):
            return
        if call.name in ("audit_creative", "audit_truth", "audit_visual"):
            self._maybe_content_lesson(call, result, node_id)
            return
        if delta == 0 or abs(delta) < LESSON_AUTO["delta_threshold"]:
            return
        if self._auto_lesson_count >= LESSON_AUTO["max_per_run"]:
            return

        category = "worked" if delta > 0 else "didnt"
        # Resumen corto del resultado (métricas) + diff de archivos para contexto
        import re
        m = re.search(r"total=(\d+)", result)
        total = f"total={m.group(1)}" if m else ""
        snippet = (result or "").strip().replace("\n", " ")[:140]
        diff_tag = f" | archivos: {file_diff}" if file_diff and file_diff != "sin cambios" else ""
        content = (
            f"[auto:{call.name}] delta {delta:+.1f} ({total}) en {node_id or 'H?'}: "
            f"{snippet}{diff_tag}"
        )
        key = (category, call.name, snippet[:80])
        if key in self._auto_lesson_keys:
            return
        self._auto_lesson_keys.add(key)
        self._auto_lesson_count += 1

        text = f"## What {category} - {datetime.now().isoformat(timespec='seconds')}\n{content}"
        self.memory.append_incremental(text)
        self._log("system", {"event": "auto_lesson", "category": category,
                             "delta": f"{delta:+.1f}", "tool": call.name,
                             "node": node_id})

    def _maybe_content_lesson(self, call, result: str, node_id: str | None) -> None:
        """Lección por CONTENIDO de una tool de diagnóstico VLM (audit_creative,
        audit_truth, audit_visual). A diferencia de la lección por delta, aquí la
        puntuación baja NO es una regresión de la tool: es un cheque concreto que
        falla. La lección ata la causa (issues) con la solución (sugerencias) al
        cheque específico, y solo se genera una vez por cheque (dedupe)."""
        import re
        if self._content_lesson_count >= LESSON_AUTO["max_per_run"]:
            return
        result = result or ""
        # extraer el score de la señal VLM y sus issues/sugerencias
        score = None
        for pat in (r"creativity_vlm=(\d+)", r"diseño_vlm=(\d+)", r"visual_vlm=(\d+)",
                    r"truth=(\d+)"):
            m = re.search(pat, result)
            if m:
                score = int(m.group(1))
                break
        if score is None:
            return
        # issues -> causa; sugerencias -> solución. Separar secciones: el bloque
        # "Issues (n):" es la causa; "Sugerencias (n):" es la solución.
        lines = result.splitlines()
        in_issues = in_sugg = False
        issues: list[str] = []
        sugg: list[str] = []
        for l in lines:
            low = l.strip().lower()
            if "issues" in low and ":" in low:
                in_issues, in_sugg = True, False
                continue
            if "sugerencias" in low and ":" in low:
                in_issues, in_sugg = False, True
                continue
            s = l.strip()
            if s.startswith("- "):
                item = s[2:].strip()
                if in_issues and item:
                    issues.append(item)
                elif in_sugg and item:
                    sugg.append(item)
        category = "worked" if score >= 85 else "didnt"
        cheque = issues[0][:80] if issues else f"{call.name}=bajo"
        key = (category, call.name, cheque[:80])
        if key in self._auto_lesson_keys:
            return
        self._auto_lesson_keys.add(key)
        self._content_lesson_count += 1
        content = (
            f"[auto:{call.name}] {call.name}={score} en {node_id or 'H?'}: "
            f"{cheque}"
        )
        if len(issues) > 1:
            content += f" | causas: {'; '.join(issues[1:3])}"
        if sugg:
            content += f" | solución: {sugg[0][:100]}"
        text = f"## What {category} - {datetime.now().isoformat(timespec='seconds')}\n{content}"
        self.memory.append_incremental(text)
        self._log("system", {"event": "auto_lesson", "category": category,
                             "tool": call.name, "score": score,
                             "node": node_id, "por": "contenido"})

    def _auto_truth_audit(self, registry, node_id: str | None) -> None:
        """Juicio de verdad automático tras cada generate_candidate: verifica que
        las partes integrantes estén CONECTADAS (repos enlazados desde la raíz) y
        compara el diseño contra referencias reales del dataset UI (WebSight).
        Es el criterio objetivo que refuerza la evolución de diseño sin depender
        de que el LLM recuerde llamar a audit_truth."""
        from types import SimpleNamespace

        try:
            tool = registry.get("audit_truth")
            if tool is None or not getattr(self, "_truth_done", False):
                pass
            if tool is None:
                return
            call = SimpleNamespace(name="audit_truth", args={"references": 1})
            result, _ = self._exec_tool(registry, call)
            self._handle_eval_result(call, result)
            self._log("system", {"event": "auto_truth", "node": node_id,
                                 "result": result[:300]})
        except Exception as e:
            self._log("system", {"event": "auto_truth_error", "error": str(e)[:200]})
        finally:
            self._truth_done = True

    def _auto_visual_audit(self, registry, node_id: str | None) -> None:
        """Crítica VLM automática tras cada generate_candidate: toma screenshot y
        pide al VLM que evalúe calidad visual + diseño. Antes de esta corrección el
        agente solo llamaba audit_truth (sin VLM) y el score visual stagnaba en
        valores bajos sin feedback que guiara las mutaciones."""
        from types import SimpleNamespace
        try:
            tool = registry.get("audit_visual")
            if tool is None:
                return
            call = SimpleNamespace(name="audit_visual", args={})
            result, _ = self._exec_tool(registry, call)
            self._handle_eval_result(call, result)
            self._log("system", {"event": "auto_visual", "node": node_id,
                                 "result": result[:300]})
        except Exception as e:
            self._log("system", {"event": "auto_visual_error", "error": str(e)[:200]})

    def _compute_novelty(self, node_id: str) -> None:
        """Novelty (B3): mide cuánto difiere el candidato nuevo del MEJOR PREVIO
        (el mejor que no sea él mismo). Lo expone como métrica del nodo y en el
        transcript, para que el agente vea si su mutación varió el diseño o solo
        repitió el seed. Un valor bajo repetido = convergencia prematura."""
        try:
            from tools.domain.evaluator import novelty_score
            node = self.tree.nodes.get(node_id)
            if node is None:
                return
            # mejor previo = el nodo con mayor total que no sea el nuevo
            prev = None
            prev_score = -1
            for nd in self.tree.nodes.values():
                if nd.id == node_id:
                    continue
                s = nd.metrics.get("total", -1)
                if s > prev_score:
                    prev, prev_score = nd, s
            if prev is None:
                return
            ref_dir = self.run_dir / "candidates" / prev.id
            cand_dir = self.run_dir / "candidates" / node_id
            if not (ref_dir / "index.html").exists() or not (cand_dir / "index.html").exists():
                return
            novelty = novelty_score(ref_dir, cand_dir)
            node.metrics["novelty"] = novelty
            self.tree.add(node)
            self._log("system", {"event": "novelty", "node": node_id,
                                 "vs": prev.id, "novelty": novelty})
        except Exception as e:
            self._log("system", {"event": "novelty_error", "error": str(e)[:200]})

    def _seed_from_workspace(self) -> None:
        """Si workspace/current tiene un candidato al arrancar, lo evalúa y lo
        registra como H0 baseline en el árbol de búsqueda (persistencia entre
        runs). Si no, no hace nada (la run genera H0 desde cero)."""
        from tools.domain.evaluator import evaluate

        src = PATHS["current"]
        if not (src / "index.html").exists():
            return
        if self.tree.nodes:
            return  # ya hay hipótesis (no re-seedar)

        m = evaluate(src)
        total = m.get("total")
        if total is None:
            return
        metrics = {k: m[k] for k in ("seo", "a11y", "performance", "responsive",
                                     "best_practices", "visual", "task", "structure")
                   if k in m and m[k] is not None}
        metrics["total"] = total
        self.tree.add(TreeNode(
            id="H0",
            parent=None,
            action="seed_workspace",
            metrics=metrics,
            status="best_branch",
            description=f"Semilla: candidato previo de workspace/current (total={total})",
        ))
        self.hypothesis_count = 1
        self.seeded = True
        self._snapshot("H0")
        self._log("eval", {"candidate": "H0", "tool": "seed_workspace",
                           "total": total, "version": "seed"})
        self._log("system", {"event": "seeded", "from": "workspace/current",
                             "total": total,
                             "note": "El candidato previo se registró como H0. Los próximos generate_candidate deben MUTARLO, no regenerar desde cero."})

    def run(self, registry, initial_url: str = "") -> str:
        self.budget.start()
        self._log("start", {"archetype": self.archetype_name, "task": self.task})

        # PERSISTENCIA ENTRE RUNS: si workspace/current ya contiene un candidato
        # (de una run previa o semilla), se evalúa y se registra como H0 baseline.
        # Así el primer generate_candidate MUTA el candidato previo en vez de
        # regenerarlo desde cero, y las mejoras visuales se acumulan entre runs.
        self._seed_from_workspace()

        while True:
            self.turn += 1
            self.budget.turn += 1

            stagnation = self.budget.register_evaluation(self._current_best_score())
            stop_reason = self.budget.done()

            if stop_reason:
                self._log("stop", {"reason": stop_reason})
                break

            # Construir prompt
            state = self._render_state(stagnation)
            prompt = (
                self._system_prompt()
                + "\n\n"
                + state
                + "\n\nTURNO ACTUAL: Decide tu próxima acción. Respóndeme con llamadas a herramientas "
                  "cuando sea necesario, o con texto si quieres razonar/cerrar."
            )

            history_slice = self._safe_history_slice()
            # Bypass de llm cache en el bucle táctico: el estado cambia cada turno
            # pero el embedding del prompt es muy similar (task/rules/ref estáticos),
            # así que con el umbral 0.80 la caché re-sirve la MISMA decisión — y
            # re-sirve también el texto de stall (p.ej. "create_patterns" JSON) con
            # lo que el agente no puede salir del bucle. Sin caché, cada turno es
            # una decisión fresca sobre el estado real.
            resp = self.llm.generate(
                prompt,
                tools=registry.schemas(),
                history=history_slice,
                use_cache=False,
            )
            self._sync_budget_cost()

            self.history.append({"role": "user", "parts": [{"text": prompt}]})

            if not resp.tool_calls:
                text = resp.text or "(sin respuesta)"
                self._log("assistant", {"text": text[:2000]})
                # El agente a veces emite JSON/meta en texto (p.ej. create_patterns
                # inventado) o razonamientos largos con la palabra 'final'; eso NO es
                # un cierre. Substrings como 'fin' en 'select_final' disparaban un
                # falso positivo que cortaba la run tras H0. Solo se considera cierre
                # un texto declarativo CORTO sin JSON/bloques y con señal explícita.
                import re as _re
                t = text.lower().strip()
                is_meta = ("create_pattern" in t or "```" in t or "{" in t)
                closed = bool(_re.search(
                    r"\b(done|fin|finalizado|final|terminado|completad[ao])\b", t))
                if closed and not is_meta and len(t) < 400:
                    # --- Gate estricto (A): no auto-detener si hay subtareas
                    # pendientes o no se alcanzó el mínimo de hipótesis --------
                    from config import MIN_HYPOTHESES
                    best_node = self.tree.best()
                    fail_ids: list[str] = []
                    has_subtasks = False
                    if best_node and best_node.id:
                        checklist = self._subtask_checklist(best_node.id)
                        has_subtasks = len(checklist) > 0
                        fail_ids = [s["id"] for s in checklist if not s.get("ok")]
                    all_ok = not fail_ids and has_subtasks  # True si checklist 100% ok; True si sin subtareas
                    hyp_ok = (self.hypothesis_count >= MIN_HYPOTHESES) if MIN_HYPOTHESES else True
                    if not all_ok and not hyp_ok:
                        self._log("system", {
                            "event": "early_close_blocked",
                            "fail_ids": fail_ids,
                            "hypotheses": self.hypothesis_count,
                            "min_h": MIN_HYPOTHESES,
                        })
                        self.history.append({
                            "role": "user",
                            "parts": [{
                                "text": (
                                    "Cierre bloqueado: subtareas en fallo "
                                    f"{fail_ids if fail_ids else '(pendientes)'}; "
                                    f"hipótesis {self.hypothesis_count}/{MIN_HYPOTHESES}. "
                                    "Resuelve con generate_candidate (estructural/funcional) "
                                    "o completa todo antes de select_final."
                                ),
                            }],
                        })
                        continue
                    # --- fin gate estricto ------------------------------------
                    if self.target_h and self.hypothesis_count <= self.target_h:
                        self._log(
                            "system",
                            {
                                "event": "target_h_bloqueado",
                                "reason": f"Objetivo {self.target_h} no alcanzado (hipótesis generadas: {self.hypothesis_count})",
                            },
                        )
                        continue
                    stop_reason = "El agente finalizó por sí mismo."
                    self._log("stop", {"reason": stop_reason})
                    break
                # Acción de texto no reconocida como cierre: si parece JSON/meta
                # (p.ej. create_patterns inventado), rechaza EXPLÍCITAMENTE para
                # romper el bucle donde el agente repite lo mismo turno a turno.
                stall = getattr(self, "_no_tool_streak", 0) + 1
                self._no_tool_streak = stall
                if is_meta:
                    self.history.append({
                        "role": "user",
                        "parts": [{
                            "text": (
                                "ACCIÓN RECHAZADA: tu acción de texto no es un cierre "
                                "válido. La meta-evolución se hace con tool_calls "
                                "(edit_skill, review_harness), no con JSON en texto "
                                "plano. Para avanzar, ejecuta generate_candidate o "
                                "audit_page ahora."
                            ),
                        }],
                    })
                    from config import AUTO_UNBLOCK_AT_STALL
                    if stall >= AUTO_UNBLOCK_AT_STALL:
                        self._no_tool_streak = 0
                        self._log("system", {"event": "auto_unblock_trigger",
                                             "turn": self.turn, "stall": stall})
                        self._auto_unblock(registry)
                        self._sync_budget_cost()
                continue

            for call in resp.tool_calls:
                self._no_tool_streak = 0
                self._handle_tool_call(registry, call)
            self._sync_budget_cost()

            # verificamos si tras ejecutar tools el presupuesto pide stop
            if self.budget.done():
                stop_reason = self.budget.done()
                self._log("stop", {"reason": stop_reason})
                break

            # compactación de contexto
            with (self.run_dir / "transcript.jsonl").open() as f:
                transcript_text = f.read()
            if self.context.should_compact(transcript_text, self.llm):
                self.history = self.context.compact(
                    self.history, self.memory.read_global_lessons()
                )
                self._log("system", {"event": "context_compacted"})

        # merge incremental -> global
        if self.memory.incremental.exists():
            lessons = self.memory.incremental.read_text()
            self.memory.append_global(lessons)
            self._log("system", {"event": "lessons_merged"})

        # WikiSkill Phase 2: consolidar en wiki + proposer post-run (fuera del loop)
        self._wiki_maintain()
        self._propose_wiki_skill()
        # Procedural Graphs self-evolution: proposer post-run (add/delete nodes/edges)
        self._propose_pg_graph()

        # exportación automática del mejor candidato si el agente no llamó a select_final
        self._export_final()

        best = self.tree.best()
        harness_end = harness_snapshot.snapshot()
        diff = harness_snapshot.diff_snapshots(self.harness_start, harness_end)
        self.db.upsert_run(
            run_id=self.run_id,
            finished=datetime.now().isoformat(),
            best_score=best.metrics.get("total") if best else None,
            best_node=best.id if best else None,
            status="done",
            harness_hash=harness_end["tree_hash"],
            harness_diff="; ".join(diff),
        )
        # SAFEEVOLVE (P9): atribuir outcomes dañinos a las lecciones recuperadas
        self._attribute_harm()
        # añadir el diff al run_config.json
        try:
            cfg_path = self.run_dir / "run_config.json"
            cfg = json.loads(cfg_path.read_text())
            cfg["harness"]["end"] = harness_end["tree_hash"]
            cfg["harness"]["diff"] = diff
            cfg_path.write_text(json.dumps(cfg, indent=2))
        except Exception:
            pass
        self.db.close()

        final = self._final_summary()
        self._log("end", {"final": final})
        return final

    def _attribute_harm(self) -> None:
        """SAFEEVOLVE reuse gate (P9): si el artefacto final de esta run contiene
        una técnica insegura (señal del heurístico), atribuye un outcome dañino a
        las lecciones globales recuperadas durante la run. Al cruzar
        SKILL_SAFETY_RETIRE_AT reuses dañinos, la lección se retira (retired=1) y
        deja de recuperarse. Nunca lanza."""
        try:
            from config import SKILL_SAFETY_ENABLED
            if not SKILL_SAFETY_ENABLED:
                return
            from tools.domain.skill_auditor import risk_span_scan
            final_dir = self.run_dir / "final"
            idx = final_dir / "index.html"
            if not idx.exists():
                return
            html = idx.read_text(errors="ignore")
            if not risk_span_scan(html):
                return
            # la run produjo un artefacto con técnica insegura: atribuir a las
            # lecciones globales que se inyectaron en el contexto (las que
            # aportaron la técnica). Atribuimos a las admitidas con señal.
            lessons = self.db.lessons(safe_only=False)
            for l in lessons:
                if l.get("admitted", 1) and risk_span_scan(l.get("content", "")):
                    self.db.record_reuse(self.run_id, l["id"],
                                         outcome="artefacto_final_inseguro", harmful=True)
            self._log("system", {"event": "skill_harm_attributed",
                                 "to_run": self.run_id})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # WikiSkill Phase 2 — Maintainer + Skill Proposer (post-loop, fuera del loop)
    # ------------------------------------------------------------------

    def _wiki_enabled(self) -> bool:
        """WIKI_ENABLED leído en runtime (permite togglear desde el orquestador
        wiki_evolve.py sin reimportar config). Gobierna la Skill Layer completa
        (maintainer + proposer + inyección de skills activos)."""
        import os
        return os.environ.get("WIKI_ENABLED", "1") != "0"

    def _wiki_maintain_enabled(self) -> bool:
        """WIKI_MAINTAIN_ENABLED leído en runtime. Altas: el gate de wiki_evolve
        evalúa el skill candidato en dev SIN consolidar wiki ni proponer skills
        (inyección de skills sí permanece vía _wiki_enabled)."""
        import os
        return os.environ.get("WIKI_MAINTAIN_ENABLED", "1") != "0"

    def _wiki_maintain(self) -> None:
        """Consolida esta run en el wiki global (memory/wiki/). No-bloqueante:
        si falla, la run termina con normalidad (log warning)."""
        try:
            if not (self._wiki_enabled() and self._wiki_maintain_enabled()):
                return
            from scripts.wiki_consolidate import consolidate
            status, _ = consolidate(dry_run=False, run_id=self.run_id, llm=self.llm)
            self._log("system", {"event": "wiki_maintained", "status": status})
        except Exception as e:
            self._log("system", {"event": "wiki_maintained", "error": str(e)[:300]})

    def _apply_skill_edits(self, content: str, edits: list) -> str:
        """Aplica operandos de patch (§E.3 finish()): append | replace | insert_after
        sobre el contenido SKILL.md actual. Devuelve el contenido resultante (o el
        original si un target no se encuentra)."""
        out = content
        for e in edits:
            if not isinstance(e, dict):
                continue
            op = (e.get("op") or "").strip()
            if op == "append":
                out = out.rstrip("\n") + "\n" + str(e.get("content", "")) + "\n"
            elif op == "replace":
                target = str(e.get("target", ""))
                if target and target in out:
                    out = out.replace(target, str(e.get("content", "")), 1)
            elif op == "insert_after":
                target = str(e.get("target", ""))
                if target and target in out:
                    out = out.replace(target, target + "\n" + str(e.get("content", "")), 1)
        return out

    def _proposer_read(self, path: str) -> str:
        """read_file restringido para el Skill Proposer: solo wiki/, runs/ y
        skills/. Devuelve el contenido o un error descriptivo (nunca lanza)."""
        p = Path(path)
        try:
            if path.startswith("memory/wiki/"):
                resolved = (PATHS["memory"] / "wiki" / path[len("memory/wiki/"):]).resolve()
            elif path.startswith("wiki/"):
                resolved = (PATHS["memory"] / "wiki" / path[len("wiki/"):]).resolve()
            elif path.startswith("runs/"):
                resolved = (PATHS["runs"] / path[len("runs/"):]).resolve()
            elif path.startswith("skills/"):
                resolved = (PATHS["skills"] / path[len("skills/"):]).resolve()
            elif path.startswith("domain/skills/"):
                resolved = (PATHS["skills"] / path[len("domain/skills/"):]).resolve()
            elif path.startswith("generated/"):
                resolved = (PATHS["domain"] / "generated" / path[len("generated/"):]).resolve()
            else:
                return f"ERROR: ruta fuera del sandbox del proposer: {path}"
        except Exception as e:
            return f"ERROR: ruta inválida '{path}': {e}"
        if not resolved.exists():
            return f"ERROR: no existe {resolved}"
        try:
            return f"{resolved}:\n" + resolved.read_text(errors="replace")[:6000]
        except Exception as e:
            return f"ERROR: no se pudo leer {resolved}: {e}"

    def _register_skill_proposal(self, parsed: dict, reads: int) -> None:
        """Registra la propuesta de skill (create/patch) en harness_edits +
        staging + skill-impact.md. Genera las propuestas pending que el gate de
        wiki_evolve evaluará contra el baseline."""
        wiki_dir = PATHS["memory"] / "wiki"
        action = (parsed.get("action") or "").strip()
        name = (parsed.get("name") or "").strip().replace(" ", "_").replace("/", "_")
        if not name or action not in ("create", "patch"):
            return

        sk_dir = PATHS["skills"] / name
        sk_path = f"skills/{name}/SKILL.md"
        existing = (sk_dir / "SKILL.md").read_text(errors="replace") if (sk_dir / "SKILL.md").exists() else ""

        if action == "create":
            after = (parsed.get("skill_md") or "").strip()
            purpose = (parsed.get("purpose_md") or "").strip()
            if not after or not purpose:
                self._log("system", {"event": "wiki_skill_proposal", "result": "missing_create_fields"})
                return
            mode = "create"
            before = ""
        else:
            edits = parsed.get("edits") or []
            if not isinstance(edits, list) or not edits:
                self._log("system", {"event": "wiki_skill_proposal", "result": "missing_edits"})
                return
            if not existing:
                self._log("system", {"event": "wiki_skill_proposal", "result": "patch_missing_skill"})
                return
            before = existing
            after = self._apply_skill_edits(existing, edits)
            purpose = (parsed.get("purpose_md") or "").strip() or "(patch)"
            mode = "patch"

        # validación YAML frontmatter del SKILL.md resultante
        import yaml as _yaml
        from tools.domain.meta_editor import _is_well_shaped
        if not after.split("---", 2)[:1] or "---" not in after:
            self._log("system", {"event": "wiki_skill_proposal", "result": "no_frontmatter"})
            return
        try:
            fm_text = after.split("---", 2)[1]
            fm = _yaml.safe_load(fm_text)
        except Exception:
            self._log("system", {"event": "wiki_skill_proposal", "result": "yaml_frontmatter_error"})
            return
        if not isinstance(fm, dict) or not fm.get("name") or not fm.get("description"):
            self._log("system", {"event": "wiki_skill_proposal", "result": "frontmatter_incomplete"})
            return
        if not _is_well_shaped(after):
            self._log("system", {"event": "wiki_skill_proposal", "result": "not_well_shaped"})
            return

        proposal_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        # staging: propuesta lista para el gate (skills/<name>/SKILL.md + PURPOSE.md)
        staged = PATHS["domain"] / ".proposals" / proposal_id / "skills" / name
        (staged / "SKILL.md").parent.mkdir(parents=True, exist_ok=True)
        (staged / "SKILL.md").write_text(after)
        (staged / "PURPOSE.md").write_text(purpose or "# PURPOSE.md\n")

        from agent.memory_db import MemoryDB
        db = MemoryDB()
        try:
            parent_id = db.latest_accepted_edit_for_file(sk_path)
            db.add_harness_edit(
                proposal_id=proposal_id, run_id=self.run_id,
                component="skills", file=sk_path, before=before, after=after,
                mode=mode, plan=f"[WIKI PROPOSER] name={name} reads={reads}",
                parent_id=parent_id,
            )
        finally:
            db.close()

        si_path = wiki_dir / "skill-impact.md"
        impact_line = (
            f"\n- **{proposal_id}** [{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
            f"run={self.run_id} | action={action} | skill={name} | file={sk_path} | "
            f"status=pending | purpose={purpose[:100].replace(chr(10), ' ')}\n"
        )
        with si_path.open("a") as f:
            f.write(impact_line)

        self._log("system", {
            "event": "wiki_skill_proposal", "result": "registered",
            "proposal_id": proposal_id, "action": action, "skill": name,
        })

    def _propose_wiki_skill(self) -> None:
        """Skill Proposer ReAct post-run (WikiSkill §E.3): lee el wiki (index,
        skill-impact, patrones, traces) de forma iterativa y propone un skill
        create|patch en domain/skills/, registrado como propuesta pending.
        No-bloqueante."""
        try:
            from config import WIKI_PROPOSER_MAX_TURNS
            if not (self._wiki_enabled() and self._wiki_maintain_enabled()):
                return
            wiki_dir = PATHS["memory"] / "wiki"
            prompt_path = PATHS["prompts"] / "wiki_proposer.txt"
            if not (wiki_dir / "index.md").exists() or not prompt_path.exists():
                return

            idx_text = (wiki_dir / "index.md").read_text(errors="replace")[:4000]
            si_path = wiki_dir / "skill-impact.md"
            si_text = si_path.read_text(errors="replace")[:2500] if si_path.exists() else "(sin entradas aún)"

            patterns_dir = wiki_dir / "patterns"
            recent_patterns = []
            if patterns_dir.is_dir():
                for p in sorted(patterns_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)[:5]:
                    recent_patterns.append(f"## {p.stem}\n{p.read_text(errors='replace')[:600]}")
            patterns_text = "\n\n".join(recent_patterns) if recent_patterns else "(sin patrones)"

            best = self.tree.best()
            best_info = f"{best.id}: total={best.metrics.get('total', '-')}" if best else "(sin mejor)"

            task_desc = f"la tarea '{self.task}' (arquetipo {self.archetype_name})"
            system = prompt_path.read_text().replace("{task_desc}", task_desc)

            run_summary = (
                f"--- CONTEXTO DE LA RUN RECIÉN TERMINADA ---\n"
                f"run_id: {self.run_id}\n"
                f"mejor_candidato: {best_info}\n"
                f"transcript: runs/{self.run_id}/transcript.jsonl (puedes leerlo con read_file)\n"
                f"--- WIKI INDEX ---\n{idx_text}\n"
                f"--- SKILL IMPACT (propuestas previas) ---\n{si_text}\n"
                f"--- PATRONES RECIENTES DEL WIKI ---\n{patterns_text}\n"
            )

            history: list[str] = []
            reads = 0
            last_raw = ""
            for _turn in range(WIKI_PROPOSER_MAX_TURNS):
                history_blk = "\n\n".join(history) if history else "(aún sin lecturas)"
                prompt = (
                    system
                    + "\n\n"
                    + run_summary
                    + "\n\n--- HISTORIAL DE LECTURAS (read_file) ---\n"
                    + history_blk
                    + "\n\nAhora responde: si necesitas leer otro archivo, emite SOLO "
                    "una línea con 'READ_FILE:<ruta>'. Si ya tienes toda la evidencia, "
                    "emite el JSON de la propuesta final (finish) o {\"action\": "
                    "\"no_action\"}."
                )
                resp = self.llm.generate(prompt, temperature=0.15)
                raw = resp.text.strip()
                last_raw = raw

                if raw.upper().startswith("READ_FILE:"):
                    path = raw.split(":", 1)[1].strip()
                    content = self._proposer_read(path)
                    history.append(f"## read_file({path})\n{content}")
                    reads += 1
                    continue

                # propuesta final o NO_ACTION
                import json as _json
                try:
                    parsed = _json.loads(raw)
                except Exception:
                    try:
                        import yaml as _yaml
                        parsed = _yaml.safe_load(raw)
                    except Exception:
                        parsed = None
                if isinstance(parsed, dict):
                    action = (parsed.get("action") or "").strip()
                    if action == "no_action" or "NO_ACTION" in raw.upper():
                        self._log("system", {"event": "wiki_skill_proposal", "result": "no_action"})
                        return
                    if reads < 2 and action in ("create", "patch"):
                        self._log("system", {"event": "wiki_skill_proposal", "result": "too_few_reads"})
                        return
                    self._register_skill_proposal(parsed, reads)
                    return
                # no es READ ni JSON: registro un fallo de parseo
                self._log("system", {"event": "wiki_skill_proposal", "result": "parse_error"})
                return

            # se agotó el número de turnos sin propuesta
            self._log("system", {"event": "wiki_skill_proposal", "result": "max_turns_reached"})
        except Exception as e:
            self._log("system", {"event": "wiki_skill_proposal", "error": str(e)[:300]})

    def _pg_proposal_enabled(self) -> bool:
        """PG Proposer activo? Desactivable con PG_GRAPH_ENABLED=0
        o PG_MAINTAIN_ENABLED=0 (no proponga en runs de evaluación/dev)."""
        if os.environ.get("PG_GRAPH_ENABLED", "1") == "0":
            return False
        return os.environ.get("PG_MAINTAIN_ENABLED", "1") != "0"

    def _register_pg_proposal(self, parsed: dict, reads: int) -> None:
        """Registra una propuesta de edición del PG (add/delete nodes/edges) en
        harness_edits + staging. La propuesta es el nuevo contenido íntegro de
        pg_graph.yaml (after); el gate la evaluará contra el baseline y revertirá
        al `before` si no mejora (Modelo de rejectión del paper)."""
        pg_path = PATHS["domain"] / "generated" / "pg_graph.yaml"
        if not pg_path.exists():
            self._log("system", {"event": "pg_graph_proposal", "result": "no_pg_file"})
            return
        before = pg_path.read_text(errors="replace")
        edits = {
            "add_nodes": parsed.get("add_nodes") or [],
            "delete_nodes": parsed.get("delete_nodes") or [],
            "add_edges": parsed.get("add_edges") or [],
            "delete_edges": parsed.get("delete_edges") or [],
        }
        if not any(v for v in edits.values()):
            self._log("system", {"event": "pg_graph_proposal", "result": "empty_edits"})
            return

        from tools.domain.pg_graph import apply_pg_edits
        after, errors = apply_pg_edits(before, edits)
        if after is None or errors:
            self._log("system", {
                "event": "pg_graph_proposal", "result": "invalid_edits",
                "errors": errors[:5],
            })
            return

        proposal_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")
        rationale = str(parsed.get("rationale") or "")[:500]
        # staging: guardar el YAML candidato para el gate
        staged = PATHS["domain"] / ".proposals" / proposal_id
        (staged / "generated").mkdir(parents=True, exist_ok=True)
        (staged / "generated" / "pg_graph.yaml").write_text(after)

        from agent.memory_db import MemoryDB
        db = MemoryDB()
        try:
            parent_id = db.latest_accepted_edit_for_file("generated/pg_graph.yaml")
            db.add_harness_edit(
                proposal_id=proposal_id, run_id=self.run_id,
                component="pg_graph", file="generated/pg_graph.yaml",
                before=before, after=after, mode="propose",
                plan=f"[PG PROPOSER] reads={reads} | {rationale}",
                parent_id=parent_id,
            )
        finally:
            db.close()

        self._log("system", {
            "event": "pg_graph_proposal", "result": "registered",
            "proposal_id": proposal_id,
            "summary": {
                "add_nodes": len(edits["add_nodes"]),
                "delete_nodes": len(edits["delete_nodes"]),
                "add_edges": len(edits["add_edges"]),
                "delete_edges": len(edits["delete_edges"]),
            },
        })

    def _propose_pg_graph(self) -> None:
        """PG Proposer ReAct post-run (Procedural Graphs, §3.3 — self-evolution):
        lee el PG actual + trazas + rejection memory y propone ediciones
        estructurales (add/delete nodes/edges). No-bloqueante."""
        try:
            from config import PG_GRAPH_ENABLED, PG_PROPOSER_MAX_TURNS
            if not PG_GRAPH_ENABLED or not self._pg_proposal_enabled():
                return
            prompt_path = PATHS["prompts"] / "pg_proposer.txt"
            pg_path = PATHS["domain"] / "generated" / "pg_graph.yaml"
            if not prompt_path.exists() or not pg_path.exists():
                return

            pg_text = pg_path.read_text(errors="replace")[:5000]
            wiki_dir = PATHS["memory"] / "wiki"
            si_path = wiki_dir / "skill-impact.md"
            si_text = si_path.read_text(errors="replace")[:2500] if si_path.exists() else "(sin entradas aún)"

            best = self.tree.best()
            best_info = f"{best.id}: total={best.metrics.get('total', '-')}" if best else "(sin mejor)"
            # rejection memory: las propuestas previas (pg_graph) y su decisión
            from agent.memory_db import MemoryDB
            db = MemoryDB()
            try:
                prev_pgs = db.harness_edits(decision="rejected", component="pg_graph", limit=10)
                if not prev_pgs:
                    prev_pgs = db.harness_edits(component="pg_graph", limit=10)
                rej_lines = [
                    f"- **{e['id']}** file={e['file']} mode={e.get('mode')} "
                    f"decision={e.get('decision')} rc={e.get('root_cause') or '-'} "
                    f"| plan={str(e.get('plan') or '')[:160]}"
                    for e in prev_pgs
                ]
            finally:
                db.close()
            rej_text = "\n".join(rej_lines) if rej_lines else "(sin propuestas previas de PG)"

            task_desc = f"la tarea '{self.task}' (arquetipo {self.archetype_name})"
            system = prompt_path.read_text().replace("{task_desc}", task_desc)

            run_summary = (
                f"--- CONTEXTO DE LA RUN RECIÉN TERMINADA ---\n"
                f"run_id: {self.run_id}\n"
                f"mejor_candidato: {best_info}\n"
                f"camino_PG: {' → '.join(self.pg_path[-10:]) if self.pg_path else '(ninguno)'}\n"
                f"transcript: runs/{self.run_id}/transcript.jsonl (puedes leerlo con read_file)\n"
                f"--- GRAFO PROCEDIMENTAL ACTUAL (domain/generated/pg_graph.yaml) ---\n{pg_text}\n"
                f"--- HISTORIAL DE PROPUESTAS PREVIAS (rejection memory) ---\n{rej_text}\n"
            )

            history: list[str] = []
            reads = 0
            # reserva siempre el último turno para la DECISIÓN: nunca se permite leer
            # en el turno final. Evita que el proposer lea hasta agotar el presupuesto
            # sin emitir propuesta/no_action (observado con el LLM real).
            max_reads = max(PG_PROPOSER_MAX_TURNS - 1, 2)
            for _turn in range(PG_PROPOSER_MAX_TURNS):
                history_blk = "\n\n".join(history) if history else "(aún sin lecturas)"
                decision_only = reads >= max_reads or _turn >= PG_PROPOSER_MAX_TURNS - 1
                if decision_only:
                    decision_hint = (
                        "No quedan turnos para más lecturas. Emite AHORA y SOLO el "
                        "JSON final: {\"action\":\"propose\", \"rationale\":\"...\", "
                        "\"add_nodes\":[...], \"delete_nodes\":[...], "
                        "\"add_edges\":[...], \"delete_edges\":[...]} "
                        "o {\"action\":\"no_action\"}."
                    )
                else:
                    decision_hint = (
                        "Ahora responde: si necesitas leer otro archivo, emite SOLO "
                        "una línea con 'READ_FILE:<ruta>'. Si ya tienes toda la evidencia, "
                        "emite el JSON de la propuesta final (finish) o {\"action\": "
                        "\"no_action\"}."
                    )
                prompt = (
                    system
                    + "\n\n"
                    + run_summary
                    + "\n\n--- HISTORIAL DE LECTURAS (read_file) ---\n"
                    + history_blk
                    + "\n\n"
                    + decision_hint
                )
                resp = self.llm.generate(prompt, temperature=0.15)
                raw = resp.text.strip()

                # READ_FILE robusto: acepta la línea 'READ_FILE:<ruta>' en cualquier
                # parte de la respuesta (el modelo a veces añade prólogo/cierre).
                rf_line = next((ln.strip() for ln in raw.splitlines()
                                if ln.strip().upper().startswith("READ_FILE:")), None)
                if rf_line:
                    if decision_only:
                        # se resiste a decidir: registramos y salimos (no fabricamos)
                        self._log("system", {
                            "event": "pg_graph_proposal", "result": "reads_exhausted",
                            "reads": reads, "raw_tail": raw[-300:],
                        })
                        return
                    path = rf_line.split(":", 1)[1].strip()
                    content = self._proposer_read(path)
                    history.append(f"## read_file({path})\n{content}")
                    reads += 1
                    continue

                import json as _json
                parsed = None
                # extracción JSON robusta: localizar el primer '{' y último '}'
                start_c, end_c = raw.find("{"), raw.rfind("}")
                if start_c >= 0 and end_c > start_c:
                    try:
                        parsed = _json.loads(raw[start_c:end_c + 1])
                    except Exception:
                        parsed = None
                if parsed is None:
                    try:
                        import yaml as _yaml
                        parsed = _yaml.safe_load(raw)
                    except Exception:
                        parsed = None
                if not isinstance(parsed, dict):
                    self._log("system", {
                        "event": "pg_graph_proposal", "result": "parse_error",
                        "raw_tail": raw[-400:],
                    })
                    return
                action = (parsed.get("action") or "").strip()
                if action in ("no_action", "NO_ACTION") or "NO_ACTION" in raw.upper():
                    self._log("system", {"event": "pg_graph_proposal", "result": "no_action"})
                    return
                if action != "propose":
                    self._log("system", {"event": "pg_graph_proposal", "result": "bad_action",
                                         "action": action})
                    return
                if reads < 2:
                    self._log("system", {"event": "pg_graph_proposal", "result": "too_few_reads",
                                         "reads": reads})
                    return
                self._register_pg_proposal(parsed, reads)
                return

            self._log("system", {
                "event": "pg_graph_proposal", "result": "max_turns_reached",
                "reads": reads, "para": raw[-400:],
            })
        except Exception as e:
            self._log("system", {"event": "pg_graph_proposal", "error": str(e)[:300]})

    def _export_final(self) -> str:
        """Copia el mejor candidato (snapshot) a runs/<run_id>/final/."""
        import shutil

        best = self.tree.best()
        if best is None:
            self._log("system", {"event": "no_final_export", "reason": "sin mejores nodos"})
            return "(sin candidato)"
        src = self.run_dir / "candidates" / best.id
        if not (src / "index.html").exists():
            src = PATHS["current"]
        if not (src / "index.html").exists():
            self._log("system", {"event": "no_final_export", "reason": "sin archivos candidatos"})
            return "(sin candidato)"
        dst = self.run_dir / "final"
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)
        self._log("system", {"event": "final_exported", "best": best.id, "to": str(dst)})
        return str(dst)

    def _current_best_score(self) -> float:
        best = self.tree.best()
        return float(best.metrics.get("total", 0.0)) if best else 0.0

    def _sync_budget_cost(self) -> None:
        """Refleja en el presupuesto el coste acumulado del LLM (llamadas del
        agente principal + subagentes), activando max_cost_usd."""
        budget_cost = getattr(self.budget, "cost_so_far", 0.0)
        llm_cost = getattr(self.llm, "cost_so_far", 0.0)
        if llm_cost > budget_cost:
            self.budget.add_turn_cost(llm_cost - budget_cost)

    def _final_summary(self) -> str:
        best = self.tree.best()
        lines = [
            f"RUN COMPLETA: {self.run_id}",
            f"Turnos usados: {self.turn}/{self.budget.max_turns}",
            f"Coste estimado: ${self.budget.cost_so_far:.4f}",
        ]
        if best:
            lines.append(f"Mejor candidato: {best.id} con total={best.metrics.get('total')}")
        else:
            lines.append("No hubo candidatos con métricas registradas.")
        lines.append(f"Transcript: {self.run_dir / 'transcript.jsonl'}")
        return "\n".join(lines)