"""
Script de normalización para alimentar el índice PEARL.
Extrae caminos exitosos de las runs de mayor score en memory.db.
"""

import sqlite3
import json
from pathlib import Path
from tools.domain.pearl_reasoner import PearlReasoner

def normalize_runs():
    db_path = Path("/mnt/c/EW/reaweb-harness/memory/memory.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Obtener runs exitosas
    successful_runs = conn.execute(
        "SELECT id FROM runs WHERE best_score >= 85.0"
    ).fetchall()
    
    run_ids = [r['id'] for r in successful_runs]
    print(f"Normalizando {len(run_ids)} runs exitosas...")
    
    pearl = PearlReasoner("bootstrap") # run_id temporal
    
    for run_id in run_ids:
        # Extraer experimentos de cada run
        exps = conn.execute(
            "SELECT action FROM experiments WHERE run_id=? ORDER BY turn ASC",
            (run_id,)
        ).fetchall()
        
        path = [e['action'] for e in exps]
        if len(path) > 2:
            # Añadir al índice de PEARL
            pearl.paths.append(path)
            
    print(f"Índice cargado con {len(pearl.paths)} trayectorias exitosas.")
    # Persistir índice si fuera necesario aquí

if __name__ == "__main__":
    normalize_runs()
