#!/usr/bin/env python3
"""Entrypoint del harness: ejecuta una run de optimización web.

Uso:
    python -m scripts.run_agent --archetype landing-page --task "landing para SaaS de IA"
    python -m scripts.run_agent --archetype ecommerce --task "tienda de sneakers" --turns 8
"""
from __future__ import annotations

import argparse

from scripts._common import run_single


def main():
    parser = argparse.ArgumentParser(description="ReaWeb harness: agente que desarrolla webs y mejora su arnés")
    parser.add_argument("--archetype", required=True, help="Arquetipo web (ver domain/archetypes/)")
    parser.add_argument("--task", required=True, help="Tarea estipulada de creación web")
    parser.add_argument("--model", default=None, help="Modelo Gemini (por defecto el de .env)")
    parser.add_argument("--turns", type=int, default=20, help="Máximo de iteraciones (H1..Hn)")
    parser.add_argument("--max-cost", type=float, default=5.0, help="Presupuesto máx en USD")
    parser.add_argument("--no-meta", action="store_true", help="Deshabilitar meta-evolución")
    parser.add_argument("--target-h", type=int, default=0,
                        help="Hipótesis objetivo (p. ej. --target-h 3 => H0..H3). No declara fin hasta alcanzarlo.")
    args = parser.parse_args()

    run_single(
        archetype=args.archetype,
        task=args.task,
        model=args.model,
        turns=args.turns,
        max_cost=args.max_cost,
        allow_meta=not args.no_meta,
        verbose=True,
        target_h=args.target_h,
    )


if __name__ == "__main__":
    main()