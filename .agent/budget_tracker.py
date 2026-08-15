"""Tracking de presupuesto (turnos, coste, tiempo) y detección de estancamiento."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from config import BUDGET_DEFAULTS


@dataclass
class BudgetTracker:
    max_turns: int = BUDGET_DEFAULTS["max_turns"]
    max_cost_usd: float = BUDGET_DEFAULTS["max_cost_usd"]
    max_wall_time_minutes: int = BUDGET_DEFAULTS["max_wall_time_minutes"]
    stagnation_advisory: int = BUDGET_DEFAULTS["stagnation_advisory"]
    stagnation_hard_stop: int = BUDGET_DEFAULTS["stagnation_hard_stop"]
    min_improvement_percent: float = BUDGET_DEFAULTS["min_improvement_percent"]

    turn: int = 0
    cost_so_far: float = 0.0
    start_time: float = 0.0
    _last_best_score: float | None = None
    _flat_turns: int = 0
    _history: list[float] = field(default_factory=list)

    def start(self) -> None:
        self.turn = 0
        self.cost_so_far = 0.0
        self.start_time = time.time()
        self._flat_turns = 0
        self._history = []

    def elapsed_minutes(self) -> float:
        if not self.start_time:
            return 0.0
        return (time.time() - self.start_time) / 60.0

    def add_turn_cost(self, usd: float) -> None:
        self.cost_so_far += usd

    def register_evaluation(self, score: float) -> str | None:
        """Registra una evaluación y devuelve aviso de stagnación si aplica."""
        self._history.append(score)
        if self._last_best_score is None:
            self._last_best_score = score
            self._flat_turns = 0
            return None

        improvement = 0.0
        if self._last_best_score and self._last_best_score > 0:
            improvement = (score - self._last_best_score) / self._last_best_score * 100.0
        if improvement >= self.min_improvement_percent:
            self._last_best_score = max(self._last_best_score, score)
            self._flat_turns = 0
            return None

        self._flat_turns += 1
        if self._flat_turns >= self.stagnation_hard_stop:
            return (
                f"STOP: {self._flat_turns} turnos sin mejora >{self.min_improvement_percent}%. "
                f"Debes seleccionar final o revertir a un candidato previo."
            )
        if self._flat_turns >= self.stagnation_advisory:
            return (
                f"ADVERTENCIA: {self._flat_turns} turnos flat. Considera explorar una "
                f"rama radicalmente diferente o revertir."
            )
        return None

    def done(self) -> str | None:
        """Devuelve motivo de fin si se agotó algún recurso; None si sigue."""
        if self.turn >= self.max_turns:
            return f"Presupuesto de turnos agotado ({self.max_turns})."
        if self.cost_so_far >= self.max_cost_usd:
            return f"Presupuesto de coste agotado (${self.max_cost_usd:.2f})."
        if self.elapsed_minutes() >= self.max_wall_time_minutes:
            return f"Tiempo agotado ({self.max_wall_time_minutes} min)."
        return None

    def turns_remaining(self) -> int:
        return max(0, self.max_turns - self.turn)

    @property
    def flat_turns(self) -> int:
        return self._flat_turns