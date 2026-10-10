#!/usr/bin/env bash
# Resume/catch-up de la batería A/B decisiva (modelo capaz) para cuentas free
# con cuota diaria agotable (gemini-3-flash-preview: 20 requests/día).
#
# Uso:
#   bash scripts/battery_resume.sh            # REPS=6 (12 runs, período multi-día)
#   REPS=4 bash scripts/battery_resume.sh     # 8 runs si se prefiere acortar
#   DRY_RUN=1 bash scripts/battery_resume.sh  # solo muestra qué lanzaría
#
# Semántica de salida (coincide con run_ab_pg_battery):
#   0  batería COMPLETA (dataset válido listo para análisis)
#   3  cuota del proveedor agotada -> BATTERY_PAUSED (resumible el próximo ciclo;
#      la ventana de flash-preview es ~24h rodante: reintenta mañana/este ciclo)
#   1  error de harness (config/red distinta de cuota)
#
# El script es idempotente: los markers con best no-None se saltan y los errores
# se reintentan (fix 37f7a45), así que se puede relanzar sin riesgo.

set -u
cd "$(dirname "$0")/.."

REPS="${REPS:-6}"
OUT="${BATTERY_OUT:-runs/battery_results_flashpreview}"
PROVIDER="${LLM_PROVIDER:-gemini}"
MODEL="${GEMINI_MODEL:-gemini-3-flash-preview}"
VISION="${VISION_PROVIDER:-groq}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "[dry-run] BATTERY_OUT=$OUT REPS=$REPS LLM_PROVIDER=$PROVIDER GEMINI_MODEL=$MODEL VISION_PROVIDER=$VISION .venv/bin/python -m scripts.run_ab_pg_battery"
  exit 0
fi

echo "== battery_resume ============================================="
echo "  OUT        = $OUT"
echo "  REPS       = $REPS"
echo "  agente     = $PROVIDER / $MODEL"
echo "  visión     = $VISION"
echo "==============================================================="

BATTERY_OUT="$OUT" REPS="$REPS" LLM_PROVIDER="$PROVIDER" \
GEMINI_MODEL="$MODEL" VISION_PROVIDER="$VISION" \
  .venv/bin/python -m scripts.run_ab_pg_battery
rc=$?

echo "== battery_resume: exit=$rc ==================================="
case "$rc" in
  0) echo "COMPLETA: dataset válido en $OUT. Analizar con el flujo habitual." ;;
  3) echo "PAUSADA: cuota agotada (ventana flash-preview ~24h rodante). Reintentar la próxima vez que se encienda/abra WSL." ;;
  *) echo "ERROR de harness (no cuota). Revisar logs." ;;
esac
exit "$rc"