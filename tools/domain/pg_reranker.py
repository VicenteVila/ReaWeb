"""PEARL §3.4 — LPRA (LLM-based Path Relevance Assessment) sobre la Skill Layer.

Re-ordena los candidatos de la skill layer por relevancia semántica con la tarea
en curso y el nodo/fase activo del Procedural Graph. El LLM emite UN JSON con
scores [0,1] por skill y el motor recorta el pool:

    pool_reranked = top_k( skills | score >= min_score, orden desc )

Es un sesgo, no una restricción: si el LLM no devuelve un JSON parseable o el
rerank está desactivado, se devuelve el orden original completo (fallback seguro).
"""
from __future__ import annotations

import json


def parse_skill_name(block: str) -> str:
    """Extrae el nombre de un skill de su bloque prompt (`## SKILL <name>`)."""
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("## SKILL "):
            return line[len("## SKILL "):].strip()
    return block.splitlines()[0].strip()[:40] if block else "(sin nombre)"


def _parse_scores(raw: str) -> list[dict]:
    """Parsea la respuesta LPRA: acepta un JSON con claves "scores" (lista de
    {skill, score}) o una lista directa. Nunca lanza."""
    text = raw.strip()
    # recortar código/backticks por si el modelo envuelve el JSON
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if isinstance(data, dict):
        data = data.get("scores")
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict) or "skill" not in item:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        out.append({"skill": str(item["skill"]), "score": max(0.0, min(1.0, score))})
    return out


def rerank_skills(blocks: list[str], llm, task: str = "",
                  pg_context: str = "", top_k: int = 3,
                  min_score: float = 0.30, temperature: float = 0.0) -> list[str]:
    """Reordena los bloques de skills por relevancia semántica (LPRA).

    Devuelve la lista de bloques reordenada y recortada. Con < 2 candidatos o si
    no se logra puntuar, devuelve los bloques originales sin filtrar."""
    if not blocks or len(blocks) < 2:
        return blocks
    if top_k <= 0:
        return blocks

    candidates = [{"skill": parse_skill_name(b), "block": b} for b in blocks]
    cand_json = json.dumps(
        [{"skill": c["skill"], "resumen": c["block"].splitlines()[0][:90]}
         for c in candidates],
        ensure_ascii=False,
    )
    prompt = (
        "Eres un evaluador de relevancia de rutas (LPRA, PEARL). Recibes la tarea "
        "actual de un agente, el nodo/fase activo de su grafo procedural, y una "
        "lista de skills candidatos. Puntúa CADA skill con su relevancia semántica "
        f"para progresar en la tarea, en escala [0,1].\n\n"
        f"TAREA: {task or '(sin especificar)'}\n"
        f"CONTEXTO PROCEDURAL: {pg_context or '(sin contexto)'}\n"
        f"CANDIDATOS:\n{cand_json}\n\n"
        "Responde SOLO con JSON:\n"
        '{"scores": [{"skill": "<nombre>", "score": 0.0..1.0}, ...]}'
        " — un elemento por candidato, sin explicaciones."
    )
    try:
        resp = llm.generate(prompt, temperature=temperature)
        scores = _parse_scores(resp.text)
    except Exception:
        return blocks  # fallback seguro: inyección completa sin filtro

    score_map = {s["skill"]: s["score"] for s in scores}
    if not score_map:
        return blocks

    ranked = [c for c in candidates if score_map.get(c["skill"], 0.0) >= min_score]
    # mantiene el orden original como desempate (las puntuaciones son correlativas)
    ranked.sort(key=lambda c: score_map.get(c["skill"], 0.0), reverse=True)
    if not ranked:
        return blocks  # si el LLM lo puntúa todo bajo, no vaciamos la inyección

    return [c["block"] for c in ranked[:top_k]]