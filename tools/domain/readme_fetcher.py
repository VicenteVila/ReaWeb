"""Tool fetch_readme: descarga los README.md de los repos de la tarea y genera
páginas HTML autocontenidas (repos/<repo>.html) para abrirlas desde las tarjetas.

Flujo por repo:
  1. Descarga raw.githubusercontent.com/<owner>/<repo>/<rama>/README.md
     (rama: main con fallback a master).
  2. Convierte markdown -> HTML con la API de GitHub (POST /markdown), o con un
     mini-convertidor local si la API falla.
  3. Sanitiza (quita scripts, iframes, on*).
  4. Escribe workspace/current/repos/<repo>.html con tema dark/light y nav de vuelta.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from urllib.parse import urlparse

from config import PATHS
from tools.base import Tool

HEADERS = {
    "User-Agent": "reaweb-harness/1.0",
    "Accept": "application/vnd.github+json",
}

TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · README</title>
<style>
  :root {{ --bg:#ffffff; --text:#1a1a1a; --accent:#6366f1; --muted:#64748b;
          --card:#f8fafc; --border:#e2e8f0; }}
  .dark {{ --bg:#0f172a; --text:#f8fafc; --accent:#818cf8; --muted:#94a3b8;
          --card:#1e293b; --border:#334155; }}
  * {{ box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,sans-serif;
         margin:0; line-height:1.6; transition:background .3s,color .3s; }}
  .topbar {{ display:flex; justify-content:space-between; align-items:center;
            padding:1rem 2rem; border-bottom:1px solid var(--border); position:sticky; top:0;
            background:var(--bg); z-index:10; }}
  .back {{ color:var(--accent); text-decoration:none; font-weight:600; }}
  .back:hover {{ text-decoration:underline; }}
  button {{ background:var(--card); color:var(--text); border:1px solid var(--border);
           border-radius:8px; padding:.4rem .8rem; cursor:pointer; }}
  main {{ max-width:860px; margin:0 auto; padding:2rem 1.5rem 4rem; }}
  h1,h2,h3,h4 {{ line-height:1.25; scroll-margin-top:4rem; }}
  h1 {{ font-size:2rem; }} h2 {{ font-size:1.5rem; border-bottom:1px solid var(--border);
       padding-bottom:.3rem; }}
  a {{ color:var(--accent); }}
  code {{ background:var(--card); padding:.15rem .35rem; border-radius:4px;
         font-size:.9em; }}
  pre {{ background:var(--card); border:1px solid var(--border); border-radius:8px;
        padding:1rem; overflow-x:auto; }}
  pre code {{ background:transparent; padding:0; }}
  img {{ max-width:100%; }}
  blockquote {{ border-left:3px solid var(--accent); margin:1rem 0; padding:.2rem 1rem;
               color:var(--muted); }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; }}
  th,td {{ border:1px solid var(--border); padding:.5rem .75rem; text-align:left; }}
  th {{ background:var(--card); }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition:none !important; }} }}
</style>
</head>
<body class="dark">
<div class="topbar">
  <a class="back" href="../index.html">&larr; Volver al portafolio</a>
  <button id="theme-toggle" aria-label="Cambiar tema">&#127769;</button>
</div>
<main>
{content}
</main>
<script>
const b=document.body,bt=document.getElementById('theme-toggle');
bt.addEventListener('click',()=>{{b.classList.toggle('dark');
  localStorage.setItem('theme',b.classList.contains('dark')?'dark':'light');}});
const s=localStorage.getItem('theme'); if(s) b.className=s;
</script>
</body>
</html>
"""


def parse_github_repos(task: str, owner: str = "VicenteVila") -> list[str]:
    """Extrae nombres de repos de github.com/<owner>/<repo> presentes en la tarea."""
    found = set()
    for m in re.finditer(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", task):
        if m.group(1) == owner:
            found.add(m.group(2).rstrip(".,;"))
    # formato lista: 'github.com/VicenteVila: TraceForge, CogniTeam, ...'
    for m in re.finditer(r"github\.com/([A-Za-z0-9_.-]+)[:\s][^.\n]{0,80}", task):
        if m.group(1) == owner:
            chunk = m.group(0)
            names = re.findall(r"\b([A-Za-z][A-Za-z0-9_.-]{2,})\b", chunk.split(":")[-1])
            found.update(names)
    return sorted(found)


def _http_get(url: str, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def _http_post_json(url: str, payload: dict, timeout: int = 15) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def _sanitize(html_text: str) -> str:
    """Quita scripts, iframes, objetos, eventos inline y URLs javascript:."""
    html_text = re.sub(r"<script[\s\S]*?</script>", "", html_text, flags=re.I)
    html_text = re.sub(r"<iframe[\s\S]*?</iframe>", "", html_text, flags=re.I)
    html_text = re.sub(r"<object[\s\S]*?</object>", "", html_text, flags=re.I)
    html_text = re.sub(r"<embed[\s\S]*?>", "", html_text, flags=re.I)
    html_text = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", html_text, flags=re.I)
    html_text = re.sub(r"\son\w+\s*=\s*[^\s>]+", "", html_text, flags=re.I)
    html_text = re.sub(r"href\s*=\s*[\"']javascript:[^\"']*[\"']", "href='#'", html_text, flags=re.I)
    return html_text


def _render_fallback(md: str) -> str:
    """Mini-convertidor markdown local (sin API): headings, pre, code, negritas, links."""
    out = []
    in_code = False
    code_lines: list[str] = []
    code_lang = ""
    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code:
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            else:
                in_code = False
                body = html_lib.escape("\n".join(code_lines))
                lang = code_lang or ""
                out.append(f"<pre><code class='language-{lang}'>{body}</code></pre>")
            continue
        if in_code:
            code_lines.append(line)
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{html_lib.escape(m.group(2))}</h{lvl}>")
            continue
        out.append(html_lib.escape(line))
    if in_code and code_lines:  # fence sin cerrar
        body = html_lib.escape("\n".join(code_lines))
        lang = code_lang or ""
        out.append(f"<pre><code class='language-{lang}'>{body}</code></pre>")
    text = "\n".join(out)
    text = re.sub(r"`([^`\n]+)`", lambda m: f"<code>{html_lib.escape(m.group(1))}</code>", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)",
                  r'<a href="\2">\1</a>', text)
    # tablas básicas
    text = re.sub(r"(?m)^(\|.*\|)\s*$", _table_row, text)
    paragraphs = re.split(r"\n{2,}", text)
    body = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith("<h") or p.startswith("<pre") or p.startswith("<table"):
            body.append(p)
        else:
            body.append(f"<p>{p}</p>")
    return "\n".join(body)


def _table_row(m):
    cells = [c.strip() for c in m.group(1).strip("|").split("|")]
    if all(set(c) <= set("-: ") and c for c in cells):
        return "<table></table>"  # separador; se ignora
    return "<table><tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr></table>"


def _download_readme(owner: str, repo: str) -> tuple[str, str]:
    """Descarga el README.md del repo probando ramas main y master."""
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
        code, body = _http_get(url)
        if code == 200 and body:
            return body, ""
    return "", f"main/master devolvieron {code}"


class FetchReadme(Tool):
    name = "fetch_readme"
    description = (
        "Descarga los README.md de los repos de github.com/VicenteVila presentes en "
        "la tarea, los convierte a HTML y genera una página autocontenida por repo "
        "(workspace/current/repos/<repo>.html) para abrir el README al hacer click "
        "en las tarjetas. Devuelve las rutas relativas a enlazar. Usa la API de "
        "GitHub con fallback local."
    )

    def __init__(self, task: str = ""):
        self.task = task
        super().__init__()

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "Propietario de GitHub (default VicenteVila)"},
                    "repos": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Repos explícitos (si se omite, se parsean de la tarea)",
                    },
                },
            },
        }

    def run(self, owner: str = "VicenteVila", repos: list[str] | None = None,
            **kwargs) -> str:
        if repos is None:
            repos = parse_github_repos(self.task, owner)
        if not repos:
            return ("ERROR: no se encontraron repos github.com/VicenteVila/<repo> "
                    "en la tarea ni en el argumento repos.")

        generated = []
        errors = []
        run_id = kwargs.get("run_id")
        for repo in repos:
            status, page = self._build_repo_page(owner, repo, run_id)
            if page is None:
                errors.append(f"{repo}: {status}")
                continue
            out = PATHS["current"] / "repos" / repo
            out.mkdir(parents=True, exist_ok=True)
            (out / "index.html").write_text(page)
            generated.append(f"repos/{repo}/index.html")

        if not generated:
            return "ERROR: no se pudo generar ningún README. Detalles: " + "; ".join(errors)
        msg = "OK: páginas README generadas:\n" + "\n".join(f"- {g}" for g in generated)
        if errors:
            msg += "\nFallos (sin página): " + "; ".join(errors)
        msg += ("\n\nActualiza las tarjetas de la landing para que cada repos enlace a "
                "su página local (p. ej. repos/TraceForge/index.html) en vez de a "
                "https://github.com.")
        return msg

    def _build_repo_page(self, owner: str, repo: str, run_id: str | None) -> tuple[str, str | None]:
        md, md_err = self._download_readme(owner, repo)
        if md_err:
            return f"README no encontrado ({md_err})", None

        # guardar el .md crudo en reference/ para trazabilidad
        if run_id:
            ref_dir = PATHS["runs"] / run_id / "reference"
            ref_dir.mkdir(parents=True, exist_ok=True)
            (ref_dir / f"{repo}.md").write_text(md)

        content = self._render_markdown(md)
        html_page = TEMPLATE.format(title=f"{repo}", content=content)
        return "ok", html_page

    def _download_readme(self, owner: str, repo: str) -> tuple[str, str]:
        return _download_readme(owner, repo)

    def _render_markdown(self, md: str) -> str:
        code, body = _http_post_json(
            "https://api.github.com/markdown",
            {"text": md, "mode": "gfm"},
        )
        if code == 200 and body:
            return _sanitize(body)
        return _sanitize(_render_fallback(md))