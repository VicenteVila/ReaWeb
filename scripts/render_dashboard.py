#!/usr/bin/env python3
"""Evaluación visual de la evolución del agente.

Genera, a partir de runs/:
  - screenshots de cada hipótesis (H0..Hn) usando Chrome headless de Windows (WSL)
  - un dashboard HTML autocondicionado (SVG + imágenes base64, sin dependencias)

Uso:
    python -m scripts.render_dashboard                       # todas las runs
    python -m scripts.render_dashboard --run <run_id>        # una run concreta
    python -m scripts.render_dashboard --no-screenshots      # solo curvas/datos
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"

CHROME_CANDIDATES = [
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
]


def find_chrome() -> str | None:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def render_screenshot(chrome: str, html_path: Path, png_path: Path, viewport: str = "1280,900") -> bool:
    """Renderiza un index.html a PNG con Chrome headless de Windows (WSL)."""
    try:
        png_path.parent.mkdir(parents=True, exist_ok=True)
        # Convertir rutas WSL -> Windows (chrome.exe es una app Windows)
        try:
            import shutil
            import subprocess as _sp

            if Path("/usr/bin/wslpath").exists():
                _win = lambda p: _sp.run(["wslpath", "-w", str(p)], capture_output=True, text=True).stdout.strip()
            else:
                raise OSError
        except OSError:
            _win = lambda p: str(p).replace("/mnt/c/", "C:\\").replace("/", "\\")

        url = "file://" + _win(html_path)
        shot = _win(png_path)
        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={viewport}",
            "--screenshot=" + shot,
            url,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)
        return png_path.exists() and png_path.stat().st_size > 0
    except Exception:
        return False


def img_to_data_uri(png_path: Path) -> str | None:
    if not png_path.exists():
        return None
    data = base64.b64encode(png_path.read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def body_excerpt(html_text: str, limit: int = 120) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html_text)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def load_run(run_dir: Path) -> dict | None:
    """Carga métricas (search_tree) + snapshots (candidates/) de una run."""
    tree_path = run_dir / "search_tree.json"
    if not tree_path.exists():
        return None
    tree = json.loads(tree_path.read_text())
    nodes = sorted(tree.get("nodes", {}).items())
    run_info = {"id": run_dir.name, "nodes": [], "candidates": []}
    for node_id, nd in nodes:
        m = nd.get("metrics", {})
        if m.get("total") is None:
            continue
        cand_dir = run_dir / "candidates" / node_id
        run_info["nodes"].append(
            {
                "id": node_id,
                "parent": nd.get("parent"),
                "metrics": m,
                "status": nd.get("status", "explored"),
                "excerpt": "",
                "snapshot_dir": str(cand_dir) if cand_dir.exists() else None,
            }
        )
        if cand_dir.exists():
            html = cand_dir / "index.html"
            if html.exists():
                run_info["nodes"][-1]["excerpt"] = body_excerpt(html.read_text(errors="replace"))
    # orden numérico (H0, H1, ... H10, H11)
    run_info["nodes"].sort(key=lambda n: int(re.search(r"(\d+)$", n["id"]).group(1)) if re.search(r"(\d+)$", n["id"]) else 0)
    return run_info


def radar_points(node) -> str:
    labels = ["seo", "a11y", "performance", "responsive", "best_practices", "visual", "task"]
    vals = [node["metrics"].get(k, 0) for k in labels]
    n = len(labels)
    cx, cy, r = 100, 100, 70
    pts = []
    for i, v in enumerate(vals):
        ang = -90 + i * (360 / n)
        import math
        rad = math.radians(ang)
        pts.append((cx + r * v / 100 * math.cos(rad), cy + r * v / 100 * math.sin(rad)))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def curve_svg(nodes) -> str:
    if len(nodes) < 2:
        return ""
    import math
    xs = [i for i in range(len(nodes))]
    totals = [n["metrics"]["total"] for n in nodes]
    w, h = 600, 250
    pad_l, pad_r, pad_t, pad_b = 50, 20, 25, 45
    ymin, ymax = min(totals), max(totals)
    if ymax == ymin:
        ymax += 1
    def px(i, y):
        return (pad_l + (w - pad_l - pad_r) * i / (len(nodes) - 1),
                pad_t + (h - pad_t - pad_b) * (1 - (y - ymin) / (ymax - ymin)))
    points = [px(i, t) for i, t in enumerate(totals)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    grid = ""
    for gy in range(0, 5):
        yy = pad_t + (h - pad_t - pad_b) * gy / 4
        grid += f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{w - pad_r}" y2="{yy:.1f}" stroke="#e2e8f0" stroke-width="1"/>'
    dots = ""
    labels = ""
    for i, (x, y) in enumerate(points):
        dots += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="#3b82f6"/>'
        labels += f'<text x="{x:.1f}" y="{h - 12}" text-anchor="middle" font-size="12">{nodes[i]["id"]}</text>'
        labels += f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="middle" font-size="11" fill="#1e293b" font-weight="600">{totals[i]}</text>'
    return f'''<svg viewBox="0 0 {w} {h}" width="100%" xmlns="http://www.w3.org/2000/svg">
{grid}
<polyline points="{poly}" fill="none" stroke="#3b82f6" stroke-width="3"/>
{dots}
{labels}
</svg>'''


def render_dashboard(runs: list[dict], screenshots: bool, chrome: str | None) -> str:
    sections = []
    for run in runs:
        nodes = run["nodes"]
        if not nodes:
            continue
        # screenshots
        for nd in nodes:
            if nd.get("snapshot_dir") and screenshots and chrome:
                png = RUNS / run["id"] / "screenshots" / (nd["id"] + ".png")
                if not png.exists():
                    ok = render_screenshot(chrome, Path(nd["snapshot_dir"]) / "index.html", png)
                else:
                    ok = True
                nd["screenshot_uri"] = img_to_data_uri(png) if ok else None
            elif nd.get("snapshot_dir"):
                png = RUNS / run["id"] / "screenshots" / (nd["id"] + ".png")
                nd["screenshot_uri"] = img_to_data_uri(png) if png.exists() else None

        best = max(nodes, key=lambda n: n["metrics"]["total"])
        baseline = nodes[0]["metrics"]["total"]
        delta = best["metrics"]["total"] - baseline

        filmstrip = []
        for nd in nodes:
            if nd.get("screenshot_uri"):
                filmstrip.append(
                    f'<figure class="shot"><img src="{nd["screenshot_uri"]}" alt="{nd["id"]}"/>'
                    f'<figcaption><b>{nd["id"]}</b> · total={nd["metrics"]["total"]} · {nd["status"]}</figcaption></figure>'
                )
        film_html = "\n".join(filmstrip) if filmstrip else '<p class="muted">Sin screenshots (usa Chrome de Windows o --no-screenshots).</p>'

        # tabla de nodos
        rows = ""
        for nd in nodes:
            m = nd["metrics"]
            rows += (
                f'<tr><td><b>{nd["id"]}</b></td><td>{nd["status"]}</td>'
                f'<td>{m.get("seo", "-")}</td><td>{m.get("a11y", "-")}</td>'
                f'<td>{m.get("performance", "-")}</td><td>{m.get("responsive", "-")}</td>'
                f'<td>{m.get("best_practices", "-")}</td>'
                f'<td>{m.get("visual", "-") if m.get("visual") is not None else "-"}</td>'
                f'<td>{m.get("task", "-") if m.get("task") is not None else "-"}</td>'
                f'<td><b>{m.get("total", "-")}</b></td></tr>'
            )
        radar_best = radar_points(best)
        radar_base = radar_points(nodes[0])

        sections.append(f'''
<section class="run">
  <h2>{run["id"]}</h2>
  <div class="meta">
      <span>Baseline <b>{baseline}</b></span> →
      <span>Mejor <b>{best["id"]} = {best["metrics"]["total"]}</b></span>
      <span>Δ <b>{delta:+d}</b></span>
  </div>
  <div class="grid2">
    <div><h3>Curva H0→Hn (total)</h3>{curve_svg(nodes)}</div>
    <div><h3>Radar mejor vs baseline</h3>
      <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
        <polygon points="{radar_base}" fill="rgba(148,163,184,0.25)" stroke="#94a3b8" stroke-width="2"/>
        <polygon points="{radar_best}" fill="rgba(59,130,246,0.30)" stroke="#3b82f6" stroke-width="2"/>
      </svg>
      <div class="legend"><span class="sw base"></span>H0 baseline <span class="sw best"></span>Mejor</div>
    </div>
  </div>
  <h3>Filmstrip (evolución visual)</h3>
  <div class="filmstrip">{film_html}</div>
  <h3>Métricas por hipótesis</h3>
  <table><thead><tr><th>H</th><th>status</th><th>seo</th><th>a11y</th><th>perf</th><th>resp</th><th>bp</th><th>visual</th><th>task</th><th>total</th></tr></thead>
  <tbody>{rows}</tbody></table>
</section>''')
    return f'''<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dashboard ReaWeb · evolución</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #f1f5f9; color: #0f172a; }}
  header {{ background: #0f172a; color: #fff; padding: 18px 28px; }}
  header h1 {{ margin: 0 0 4px; font-size: 20px; }}
  header p {{ margin: 0; color: #cbd5e1; font-size: 13px; }}
  main {{ max-width: 1200px; margin: 22px auto; padding: 0 20px; }}
  section.run {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; margin-bottom: 26px; }}
  .meta {{ display: flex; gap: 14px; flex-wrap: wrap; color: #334155; margin: 6px 0 12px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 26px; }}
  @media (max-width: 800px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
  .filmstrip {{ display: flex; gap: 14px; overflow-x: auto; padding-bottom: 10px; }}
  figure.shot {{ flex: 0 0 280px; margin: 0; }}
  .filmstrip img {{ width: 280px; border: 1px solid #cbd5e1; border-radius: 8px; }}
  figcaption {{ font-size: 12px; color: #475569; margin-top: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 6px 10px; text-align: center; }}
  th {{ background: #f8fafc; }}
  .muted {{ color: #64748b; }}
  .legend {{ font-size: 12px; color: #475569; }}
  .legend .sw {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 4px; }}
  .legend .sw.base {{ background: #94a3b8; }}
  .legend .sw.best {{ background: #3b82f6; }}
</style></head>
<body><header><h1>Dashboard ReaWeb · Evolución de hipótesis</h1>
<p>Generado {datetime.now().astimezone().isoformat(timespec="seconds")} · {len([r for r in runs if r["nodes"]])} runs con candidatos · screenshots={screenshots}</p>
</header><main>{''.join(sections)}</main></body></html>'''


def main():
    ap = argparse.ArgumentParser(description="Dashboard visual de evolución del agente")
    ap.add_argument("--run", default=None, help="Solo una run (run_id o nombre de carpeta)")
    ap.add_argument("--no-screenshots", action="store_true", help="No generar screenshots (solo curvas/datos)")
    args = ap.parse_args()

    runs = []
    for d in sorted(RUNS.iterdir()):
        if not d.is_dir():
            continue
        if args.run and args.run not in (d.name, d.name.split("--")[-1]):
            continue
        info = load_run(d)
        if info and info["nodes"]:
            runs.append(info)

    if not runs:
        print("No hay runs con candidatos evaluados.")
        return

    chrome = None if args.no_screenshots else find_chrome()
    if chrome:
        print(f"Render MVP: Chrome encontrado en {chrome}")
    elif not args.no_screenshots:
        print("Aviso: no se encontró Chrome de Windows. Genero dashboard sin screenshots.")

    html = render_dashboard(runs, screenshots=not args.no_screenshots, chrome=chrome)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    if args.run:
        # con --run, el dashboard vive DENTRO de esa run
        run_dir = None
        for d in sorted(RUNS.iterdir()):
            if d.is_dir() and args.run in (d.name, d.name.split("--")[-1]):
                run_dir = d
                break
        out_dir = run_dir or RUNS
    else:
        out_dir = RUNS
    out = out_dir / f"dashboard_{ts}.html"
    out.write_text(html)
    print(f"Dashboard escrito en: {out}")
    print("Ábrelo con doble clic en el navegador.")


if __name__ == "__main__":
    main()