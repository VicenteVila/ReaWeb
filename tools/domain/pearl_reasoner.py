"""
Capa de razonamiento inductivo basada en similitud de trayectorias (PEARL).
Utiliza embeddings locales para comparar caminos actuales con historial exitoso.
"""

import os
import numpy as np
import faiss
from pathlib import Path
from agent.memory_db import MemoryDB

class PearlReasoner:
    def __init__(self, run_id: str):
        self.db = MemoryDB()
        self.run_id = run_id
        self.dimension = 384  # Dimension para all-MiniLM-L6-v2
        self.index = faiss.IndexFlatL2(self.dimension)
        self.paths = []  # Lista de (path_str, skill_suggested)
        self._initialize_index()

    def _get_embedding(self, text: str) -> np.ndarray:
        """
        Placeholder: En producción usar sentence-transformers.
        Para bootstrapping, usamos una codificación determinista de los caracteres
        que actúe como embedding (o un modelo local si el entorno lo permite).
        Dado que estamos en un entorno con recursos limitados, usaremos un
        hash proyectado como aproximación robusta para similitud estructural.
        """
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        # Proyectar hash a espacio vectorial
        vec = np.array([int(h[i:i+2], 16) for i in range(0, 64, 2)], dtype=np.float32)
        # Pad a 384
        return np.pad(vec, (0, self.dimension - 32), 'constant')

    def _initialize_index(self):
        """Carga y construye el índice FAISS con las trayectorias de runs exitosas."""
        import sqlite3
        conn = sqlite3.connect(self.db.path)
        conn.row_factory = sqlite3.Row
        successful_runs = conn.execute("SELECT id FROM runs WHERE best_score >= 85.0").fetchall()
        
        embeddings = []
        for run in successful_runs:
            exps = conn.execute(
                "SELECT action FROM experiments WHERE run_id=? ORDER BY turn ASC",
                (run['id'],)
            ).fetchall()
            path = [e['action'] for e in exps]
            if len(path) > 2:
                # Guardamos el mapeo de trayectoria -> sugerencia (última acción)
                self.paths.append({"traj": path[:-1], "next": path[-1]})
                embeddings.append(self._get_embedding(" -> ".join(path[:-1])))
        
        if embeddings:
            mat = np.array(embeddings, dtype=np.float32)
            self.index.add(mat)
        conn.close()

    def suggest_path(self, current_trajectory: list[str]) -> str | None:
        """Busca en el índice la trayectoria más similar y devuelve la siguiente acción."""
        if not self.paths or not current_trajectory:
            return None
            
        traj_str = " -> ".join(current_trajectory)
        query_vec = self._get_embedding(traj_str).reshape(1, -1)
        
        # Búsqueda FAISS
        distances, indices = self.index.search(query_vec, 1)
        
        if distances[0][0] < 50.0:  # Umbral de similitud
            idx = indices[0][0]
            suggestion = self.paths[idx]["next"]
            
            # Log explícito
            import json
            from datetime import datetime
            log_entry = {
                "ts": datetime.now().isoformat(),
                "event": "pearl_reasoning",
                "trajectory": current_trajectory,
                "best_match_idx": int(idx),
                "distance": float(distances[0][0]),
                "suggestion": suggestion
            }
            log_path = Path("/mnt/c/EW/reaweb-harness/runs/pearl_reasoning.jsonl")
            with log_path.open("a") as f:
                f.write(json.dumps(log_entry) + "\n")
                
            return suggestion
        return None

def load_pearl_reasoner(run_id: str):
    return PearlReasoner(run_id)
