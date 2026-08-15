"""Bucle principal del agente ReASearch: re-emisión de estado, tool-calling,
memoria, presupuesto y compactación de contexto."""
from __future__ import annotations

import json
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
from config import CONTEXT_DEFAULTS, ensure_dirs, PATHS


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
    ):
        self.llm = llm
        self.archetype_name = archetype_name
        self.task = task
        self.rules = rules
        self.stack = stack
        self.allow_meta_edits = allow_meta_edits
        self.verbose = verbose
        self.initial_url = initial_url

        run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "--" + archetype_name
        self.run_dir = run_dir or (PATHS["runs"] / run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = self.run_dir.name

        self.budget = BudgetTracker(max_turns=max_turns, max_cost_usd=max_cost_usd)
        self.db = MemoryDB()
        self.memory = Memory(run_dir=self.run_dir, db=self.db, run_id=self.run_id)
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
        self.last_transcript: list = []
        self.target_h = target_h
        self.hypothesis_count = 0

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
        return base + meta_note + target_note + rules_block

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

    def _render_state(self, stagnation: str | None) -> str:
        env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PATHS["prompts"])))
        tmpl = env.get_template("state_template.j2")
        best = self.tree.best()
        best_fields = {
            "id": best.id if best else "-",
            "metrics_summary": (
                ", ".join(f"{k}={v}" for k, v in sorted(best.metrics.items()) if k != "total")
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
        return tmpl.render(
            turn_number=self.turn,
            archetype_name=self.archetype_name,
            task=self.task,
            initial_url=self.initial_url,
            turns_remaining=self.budget.turns_remaining(),
            turns_total=self.budget.max_turns,
            cost_so_far=self.budget.cost_so_far,
            best=best_fields,
            recent=recent,
            tree=self.tree.summary(max_nodes=CONTEXT_DEFAULTS["search_tree_max_nodes"]),
            lessons=self.memory.read_global_lessons()[:3000],
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
            result = tool.run(**kwargs)
        except Exception as e:
            result = f"ERROR ejecutando {call.name}: {e}"
        self._log("tool", {"tool": call.name, "args": call.args, "result": result[:2000]})
        return result, {}

    def _handle_eval_result(self, call, result: str) -> str | None:
        """Interpreta métricas de generate_candidate o audit_page y actualiza el
        árbol de búsqueda en términos de hipótesis H0..Hn.

        - generate_candidate: crea una NUEVA hipótesis H<i> (baseline H0 la primera).
        - audit_page: CONFIRMA (doble verificación) la hipótesis actual, actualizando
          sus métricas sin crear nodos duplicados.
        """
        if call.name not in ("generate_candidate", "audit_page"):
            return None
        import re

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
        }
        for token, key in mapping.items():
            m2 = re.search(token, result)
            if m2:
                metrics[key] = int(m2.group(1))
        metrics["total"] = total

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

    def run(self, registry, initial_url: str = "") -> str:
        self.budget.start()
        self._log("start", {"archetype": self.archetype_name, "task": self.task})

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
            resp = self.llm.generate(
                prompt,
                tools=registry.schemas(),
                history=history_slice,
            )

            self.history.append({"role": "user", "parts": [{"text": prompt}]})

            if not resp.tool_calls:
                text = resp.text or "(sin respuesta)"
                self._log("assistant", {"text": text[:2000]})
                # si el agente no invoca tools pero dice DONE o FIN, terminar
                if any(k in text.lower() for k in ("done", "fin", "finalizado", "terminado")):
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
                continue

            for call in resp.tool_calls:
                prev_best = self._current_best_score()
                result, _ = self._exec_tool(registry, call)
                self.history.append({"role": "model", "parts": [{"function_call": {"name": call.name, "args": call.args}}]})
                self.history.append({"role": "user", "parts": [{"function_response": {"name": call.name, "response": {"result": result}}}]})
                node_id = self._handle_eval_result(call, result)
                delta = self._current_best_score() - prev_best
                self.memory.add_experiment(
                    Experiment(
                        id=f"t{self.turn}",
                        action=call.name,
                        result=result[:200],
                        delta=f"{delta:+.1f}",
                        node_id=node_id,
                    )
                )
                if call.name == "generate_candidate" and node_id is not None:
                    self._snapshot(node_id)

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