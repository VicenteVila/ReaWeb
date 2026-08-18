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
        # CHECKLIST DE SUBTAREAS (loop F1): estado ok/fail por subtarea del mejor
        best_fields["subtasks"] = self._subtask_checklist(best.id if best else None)
        best_fields["novelty"] = best.metrics.get("novelty") if best else None
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
            seeded=getattr(self, "seeded", False),
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
            result = tool.run(**kwargs)
        except Exception as e:
            result = f"ERROR ejecutando {call.name}: {e}"
        # Guardar los tests funcionales si la tool los expone (loop F1): permite
        # al checklist de subtareas marcar ok/fail funcional sin re-ejecutar Chrome.
        if hasattr(tool, "last_functional_tests") and tool.last_functional_tests:
            self._last_functional_tests = tool.last_functional_tests
        self._log("tool", {"tool": call.name, "args": call.args, "result": result[:2000]})
        return result, {}

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
                           result: str) -> None:
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
        # Resumen corto del resultado (métricas) para dar contexto a la lección.
        import re
        m = re.search(r"total=(\d+)", result)
        total = f"total={m.group(1)}" if m else ""
        snippet = (result or "").strip().replace("\n", " ")[:140]
        content = (
            f"[auto:{call.name}] delta {delta:+.1f} ({total}) en {node_id or 'H?'}: "
            f"{snippet}"
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
            resp = self.llm.generate(
                prompt,
                tools=registry.schemas(),
                history=history_slice,
            )
            self._sync_budget_cost()

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
                # delta = total del nodo recién evaluado vs mejor previo. NO usar
                # best_after - best_before: el mejor global nunca baja (los nodos
                # peores no lo reemplazan), así que un candidato regresivo daría
                # delta=0 y nunca generaría lección "didnt".
                node_total = (
                    float(self.tree.nodes[node_id].metrics.get("total", 0.0))
                    if node_id and node_id in self.tree.nodes else 0.0
                )
                delta = node_total - prev_best
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
                    self._auto_truth_audit(registry, node_id)
                if call.name == "generate_candidate" and node_id is not None:
                    self._compute_novelty(node_id)
                self._maybe_auto_lesson(call, delta, node_id, result)
                if node_id is not None and call.name in ("generate_candidate", "audit_page"):
                    self._maybe_subtask_lesson(node_id)
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