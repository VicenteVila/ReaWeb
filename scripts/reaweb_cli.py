"""CLI simplificada de ReaWeb (entry point `reaweb`).

Ofrece la experiencia "prompt y obtén tu web" con defaults sensatos:

    reaweb "landing para un SaaS de analítica de IA"
    reaweb --quick "landing para un SaaS de analítica de IA"
    reaweb --archetype ecommerce --url https://ejemplo.com "tienda de sneakers"

El modo `--quick` usa un presupuesto mínimo (H0→H1, sin meta-evolución, sin VLM)
para resultados rápidos y baratos; el modo por defecto es la suite completa de
investigación.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Presupuesto del modo rápido (H0 -> H1 -> final)
QUICK_TURNS = 4
QUICK_MAX_COST = 0.5

# Presupuesto por defecto de la suite completa de investigación
RESEARCH_TURNS = 16
RESEARCH_MAX_COST = 5.0

# Mapeo de arquetipos disponibles (para el autocompletado de --archetype)
ARCHETYPES = sorted(
    p.name for p in (Path(__file__).resolve().parent.parent / "domain" / "archetypes").iterdir()
    if p.is_dir()
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="reaweb",
        description="ReaWeb: agente ReASearch que desarrolla webs y evoluciona su propio harness",
        epilog="Ejemplos:\n"
               "  reaweb \"landing para un SaaS de IA\"\n"
               "  reaweb --quick \"landing para un SaaS de IA\"\n"
               "  reaweb --archetype ecommerce \"tienda de sneakers\"\n"
               "  reaweb --url https://ejemplo.com \"landing SaaS adaptada\"",
    )
    parser.add_argument("task", help="Tarea estipulada de creación web")
    parser.add_argument("--archetype", default="landing-page",
                        help=f"Arquetipo web. Default: landing-page. Disponibles: {', '.join(ARCHETYPES)}")
    parser.add_argument("--quick", action="store_true",
                        help=f"Modo rápido: máx {QUICK_TURNS} turnos, ${QUICK_MAX_COST}, sin meta-evolución ni VLM")
    parser.add_argument("--url", default="", help="URL de referencia a analizar (HTML crudo) para adaptar su contenido como H0")
    parser.add_argument("--model", default=None, help="Modelo Gemini (por defecto el de .env)")
    parser.add_argument("--turns", type=int, default=None, help="Máximo de iteraciones (reemplaza el default del modo)")
    parser.add_argument("--max-cost", type=float, default=None, help="Presupuesto máx en USD (reemplaza el default del modo)")
    parser.add_argument("--target-h", type=int, default=0, help="Hipótesis objetivo (p. ej. 3 => H0..H3). No declara fin hasta alcanzarlo.")
    parser.add_argument("--no-cache", action="store_true", help="Deshabilitar la caché semántica de LLM")
    parser.add_argument("--no-meta", action="store_true", help="Deshabilitar meta-evolución")
    parser.add_argument("--verbose", action="store_true", help="Mostrar el resumen final detallado")
    args = parser.parse_args(argv)

    quick = args.quick
    turns = args.turns or (QUICK_TURNS if quick else RESEARCH_TURNS)
    max_cost = args.max_cost or (QUICK_MAX_COST if quick else RESEARCH_MAX_COST)
    allow_meta = not args.no_meta and not quick
    use_cache = not args.no_cache

    if quick:
        print(f"[reaweb] modo RÁPIDO: {turns} turnos, ${max_cost}, sin meta-evolución, sin crítico VLM")
    else:
        print(f"[reaweb] modo INVESTIGACIÓN: {turns} turnos, ${max_cost}, meta-evolución activa")

    from scripts._common import run_single

    agent = run_single(
        archetype=args.archetype,
        task=args.task,
        model=args.model,
        turns=turns,
        max_cost=max_cost,
        allow_meta=allow_meta,
        verbose=args.verbose,
        target_h=args.target_h,
        initial_url=args.url,
        use_cache=use_cache,
    )
    print(f"\n[reaweb] Salida final: {agent.run_dir / 'final'}")
    print(f"[reaweb] Run completa: {agent.run_dir}")


if __name__ == "__main__":
    main()
