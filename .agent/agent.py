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
from agent.state import ContextManager, Experiment, Memory, SearchTree, TreeNode
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
    ):
        self.llm = llm
        self.archetype_name = archetype_name
        self.task = task
        self.rules = rules
        self.stack = stack
        self.allow_meta_edits = allow_meta_edits
        self.verbose = verbose

        run_id = datetime.now().strftime("%Y%m%dT%H%M%S") + "--" + archetype_name
        self.run_dir = run_dir or (PATHS["runs"] / run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_id = self.run_dir.name

        self.budget = BudgetTracker(max_turns=max_turns, max_cost_usd=max_cost_usd)
        self.memory = Memory(run_dir=self.run_dir)
        self.tree = SearchTree(path=self.run_dir / "search_tree.json")
        self.context = ContextManager(
            threshold_tokens=CONTEXT_DEFAULTS["compaction_threshold_tokens"],
            max_history=CONTEXT_DEFAULTS["max_history_turns"],
        )
        self.history: list = []
        self.turn = 0
        self.last_transcript: list = []

        # registrar run en transcript
        (self.run_dir / "run_config.json").write_text(
            json.dumps(
                {
                    "archetype": archetype_name,
                    "task": task,
                    "model": getattr(llm, "model", "?"),
                    "max_turns": max_turns,
                    "started": datetime.now().isoformat(),
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
        rules_block = ""
        if self.rules:
            rules_block = "\n\n# REGLAS Y STACK DEL ARQUETIPO (contexto precargado)\n" + self.rules[:4000]
        return base + meta_note + rules_block

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
            turns_remaining=self.budget.turns_remaining(),
            turns_total=self.budget.max_turns,
            cost_so_far=self.budget.cost_so_far,
            best=best_fields,
            recent=recent,
            tree=self.tree.summary(max_nodes=CONTEXT_DEFAULTS["search_tree_max_nodes"]),
            lessons=self.memory.read_global_lessons()[:3000],
            stagnation=stagnation,
            last_action_summary=self._last_action_summary(),
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
        """Interpreta el resultado de audit_page para actualizar árbol y presupuesto."""
        if call.name != "audit_page" or "total=" not in result:
            return None
        try:
            import re

            m = re.search(r"total=(\d+)", result)
            total = int(m.group(1)) if m else 0
            metrics = {}
            mapping = {
                "seo=": "seo",
                "a11y=": "a11y",
                "perf=": "performance",
                "resp=": "responsive",
                "bp=": "best_practices",
            }
            for token, key in mapping.items():
                m2 = re.search(rf"{token}(\d+)", result)
                if m2:
                    metrics[key] = int(m2.group(1))
            metrics["total"] = total
            node_id = f"v{self.turn:03d}"
            prev_best = self.tree.best()
            prev_score = prev_best.metrics.get("total", -1) if prev_best else -1
            self.tree.add(
                TreeNode(
                    id=node_id,
                    parent=prev_best.id if prev_best else None,
                    action=self.last_transcript[-1].get("tool", "") if self.last_transcript else "",
                    metrics=metrics,
                    status="best_branch" if total >= prev_score else "explored",
                )
            )
            best_prev = prev_score if prev_score >= 0 else None
            delta = ""
            if best_prev is not None:
                delta = f"{total - best_prev:+d}"
                self._log("eval", {"candidate": node_id, "total": total, "delta": delta})
            else:
                self._log("eval", {"candidate": node_id, "total": total, "delta": None})
            return node_id
        except Exception as e:
            return None

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
                    stop_reason = "El agente finalizó por sí mismo."
                    self._log("stop", {"reason": stop_reason})
                    break
                continue

            for call in resp.tool_calls:
                result, _ = self._exec_tool(registry, call)
                self.history.append({"role": "model", "parts": [{"function_call": {"name": call.name, "args": call.args}}]})
                self.history.append({"role": "user", "parts": [{"function_response": {"name": call.name, "response": {"result": result}}}]})
                self.memory.add_experiment(
                    Experiment(
                        id=f"t{self.turn}",
                        action=call.name,
                        result=result[:200],
                        delta="",
                    )
                )
                node_id = self._handle_eval_result(call, result)
                if node_id is not None:
                    # tmp: actualizar la última métrica como evaluación
                    pass

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

        final = self._final_summary()
        self._log("end", {"final": final})
        return final

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