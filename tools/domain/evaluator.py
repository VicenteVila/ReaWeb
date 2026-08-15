"""Evaluador ligero de sitios web estáticos. Analiza archivos HTML/CSS/JS sin
necesidad de navegador y produce métricas estilo Lighthouse (0-100 por categoría).

Categorías: seo, a11y, performance, responsive, best_practices
"""
from __future__ import annotations

import re
from pathlib import Path

SEO_CHECKS = {
    "title": ("<title> presente", lambda h: "<title" in h and "</title>" in h),
    "title_len": (
        "title < 60 chars",
        lambda h: len(re.sub(r"<[^>]+>", "", re.search(r"<title.*?>(.*?)</title>", h, re.S).group(1)) if re.search(r"<title.*?>(.*?)</title>", h, re.S) else "") < 60,
    ),
    "meta_desc": (
        'meta description presente',
        lambda h: re.search(r'<meta\s+name=["\']description', h) is not None,
    ),
    "og": ("Open Graph tags", lambda h: 'property="og:title"' in h or "og:title" in h),
    "h1": ("Un solo <h1>", lambda h: len(re.findall(r"<h1[ >]", h)) == 1),
    "lang": ("Atributo lang en <html>", lambda h: re.search(r'<html[^>]*\blang=', h) is not None),
    "viewport": ("viewport meta", lambda h: 'name="viewport"' in h or "name='viewport'" in h),
    "canonical": ("canonical link", lambda h: 'rel="canonical"' in h),
}

A11Y_CHECKS = {
    "alt_images": (
        "imágenes con alt",
        lambda h: all(re.search(r'alt=["\']', tag_attrs) is not None for tag_attrs in re.findall(r"<img\b([^>]*)>", h))
        if re.findall(r"<img\b([^>]*)>", h) else True,
    ),
    "labels_inputs": (
        "inputs con label o aria-label",
        lambda h: _inputs_labeled(h),
    ),
    "skip_link": ("skip link", lambda h: re.search(r'class=["\'][^"\']*skip', h) is not None or "skip-link" in h),
    "lang_set": ("lang set (a11y)", lambda h: re.search(r'<html[^>]*\blang=', h) is not None),
    "semantic": ("usa main/section/nav", lambda h: re.search(r"<(main|section|nav|article)\b", h) is not None),
}

PERF_CHECKS = {
    "html_size": ("HTML < 100KB", lambda h: len(h) < 100_000),
    "no_inline_css": ("CSS en archivo, no inline masivo", lambda h: len(re.findall(r"<style[ >]", h)) <= 2),
    "no_inline_js": ("JS en archivo, no inline masivo", lambda h: len(re.findall(r"<script[^>]*>", h)) <= 3),
    "modern_img": ("imágenes en webp/avif", lambda h: _has_modern_images(h)),
    "defer_js": ("scripts con defer/type=module", lambda h: _scripts_async(h)),
}

RESP_CHECKS = {
    "viewport_mobile": ("viewport para mobile", lambda h: 'name="viewport"' in h),
    "media_queries": ("media queries en CSS", lambda css: "@media" in css),
    "flexgrid": ("usa flex o grid", lambda css: "display:flex" in css or "display: grid" in css),
    "img_responsive": ("imágenes con width/height o max-width", lambda h: _img_responsive(h)),
}

BP_CHECKS = {
    "doctype": ("doctype presente", lambda h: h.lstrip().lower().startswith("<!doctype html>")),
    "no_console": ("sin console.log", lambda js: "console.log" not in js),
    "charset": ("meta charset", lambda h: 'charset="utf-8"' in h or "charset=UTF-8" in h),
    "favicon": ("favicon link", lambda h: 'rel="icon"' in h or 'rel="shortcut icon"' in h),
}


def extract_requirements(task: str, max_items: int = 8) -> list[str]:
    """Extrae requisitos verificables de la tarea estipulada:
    - URLs de repositorios (github.com/usuario/repo, gitlab.com/..., etc.)
    - menciones 'github.com/usuario' (para exigir al menos enlaces a ese perfil)
    - nombres de repos en PascalCase cuando la tarea menciona una cuenta github/gitlab
    """
    reqs: list[str] = []
    # 1) URLs de repos completas (se ignoran templates/placeholders con < o ${)
    for m in re.finditer(r"https?://[^\s)\"']+", task):
        url = m.group(0).rstrip(",.;")
        if "<" in url or "${" in url or "{" in url:
            continue
        if any(h in url for h in ("github.com", "gitlab.com", "bitbucket.org", "hub.docker.com")):
            if url not in reqs:
                reqs.append(url)

    # 2) cuentas owner mencionadas (github.com/usuario / gitlab.com/usuario)
    owners = set()
    for m in re.finditer(r"(?:github|gitlab)\.com/([A-Za-z0-9_.-]+)", task):
        owners.add(m.group(1))
    for owner in sorted(owners):
        base = f"github.com/{owner}"
        if not any(f"{base}/" in r for r in reqs) and base not in reqs:
            reqs.append(base)

    # 3) nombres de repos en PascalCase (se exige que aparezcan en el código)
    if owners:
        seen = set()
        skip = {"HTML", "CSS", "JS", "GitHub", "Python", "JavaScript", "TypeScript",
                "Landing", "Portfolio", "LandingPage", "Vicente", "Vila", "Repo", "Repos",
                "Cada", "Para", "Con", "Sin", "Una", "Los", "Las", "Son", "Web"}
        for m in re.finditer(r"([A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)", task):
            name = m.group(1)
            if name in seen or name in skip or len(name) < 4:
                continue
            seen.add(name)
            if name not in reqs:
                reqs.append(name)
            if len(reqs) >= max_items:
                break
    return list(dict.fromkeys(reqs[:max_items]))


def _inputs_labeled(h: str) -> bool:
    inputs = re.findall(r"<input\b([^>]*)>", h)
    if not inputs:
        return True
    for attrs in inputs:
        if re.search(r'aria-label=["\']', attrs) or re.search(r'id=["\']', attrs):
            continue
        # input tipo hidden no necesita label
        if 'type="hidden"' in attrs:
            continue
        return False
    return True


def _has_modern_images(h: str) -> bool:
    imgs = re.findall(r'src=["\']([^"\']+)["\']', h)
    if not imgs:
        # Sin imágenes -> se considera OK
        return True
    return any(ext in i.lower() for i in imgs for ext in (".webp", ".avif"))


def _scripts_async(h: str) -> bool:
    scripts = re.findall(r"<script\b([^>]*)>", h)
    if not scripts:
        return True
    return any("defer" in s or "type=\"module\"" in s for s in scripts)


def _img_responsive(h: str) -> bool:
    imgs = re.findall(r"<img\b([^>]*)>", h)
    if not imgs:
        return True
    ok = 0
    for attrs in imgs:
        if "width=" in attrs or "max-width" in attrs or "height=" in attrs or 'srcset' in attrs:
            ok += 1
    return ok == len(imgs)


def _score(checks: list[tuple[str, str, object]], context: str) -> tuple[int, list[str]]:
    passed = [name for _, name, fn in checks if bool(fn(context))]
    fails = [key for key, name, fn in checks if not bool(fn(context))]
    pct = int(100 * len(passed) / len(checks)) if checks else 100
    return pct, fails


def evaluate(project_dir: str | Path, requirements: list[str] | None = None) -> dict:
    """Evalúa un proyecto web estático. Devuelve métricas por categoría y total.

    requirements: lista de subcadenas que DEBEN aparecer en el código (html+css+js)
    concatenado. Si se pasan, se añade la categoría 'task' al total (requisitos de
    la tarea estipulada presentes). Si no, 'task' se ignora (total = media de 5 ejes).
    """
    project_dir = Path(project_dir)
    html_files = sorted(project_dir.rglob("*.html"))
    css_text = " ".join(p.read_text(errors="replace") for p in project_dir.rglob("*.css"))
    js_text = " ".join(p.read_text(errors="replace") for p in project_dir.rglob("*.js"))

    if not html_files:
        return {
            "error": "No hay archivos HTML",
            "total": 0,
            "files": 0,
        }

    h = html_files[0].read_text(errors="replace")
    n_html = len(html_files)

    seo, seo_fails = _score([(k,) + v for k, v in SEO_CHECKS.items()], h)
    a11y, a11y_fails = _score([(k,) + v for k, v in A11Y_CHECKS.items()], h)
    perf, perf_fails = _score([(k,) + v for k, v in PERF_CHECKS.items()], h)
    resp, resp_fails = _score([(k,) + v for k, v in RESP_CHECKS.items()], h)
    bp, bp_fails = _score([(k,) + v for k, v in BP_CHECKS.items()], h)

    # Categoría 'task': requisitos de la tarea presentes en el código
    requirements = requirements or []
    combined = h + "\n" + css_text + "\n" + js_text
    task_fails = [r for r in requirements if r not in combined]
    task = int(100 * (len(requirements) - len(task_fails)) / len(requirements)) if requirements else None

    html_bytes = sum(p.stat().st_size for p in html_files)
    css_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.css"))
    js_bytes = sum(p.stat().st_size for p in project_dir.rglob("*.js"))
    img_bytes = sum(p.stat().st_size for p in project_dir.rglob("*")
                    if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"))

    if task is not None:
        total = int((seo + a11y + perf + resp + bp + task) / 6)
    else:
        total = int((seo + a11y + perf + resp + bp) / 5)

    return {
        "total": total,
        "seo": seo,
        "a11y": a11y,
        "performance": perf,
        "responsive": resp,
        "best_practices": bp,
        "task": task,
        "failures": {
            "seo": seo_fails,
            "a11y": a11y_fails,
            "performance": perf_fails,
            "responsive": resp_fails,
            "best_practices": bp_fails,
            "task": task_fails,
        },
        "files": {
            "html": n_html,
            "total_html_kb": round(html_bytes / 1024, 1),
            "total_css_kb": round(css_bytes / 1024, 1),
            "total_js_kb": round(js_bytes / 1024, 1),
            "total_img_kb": round(img_bytes / 1024, 1),
        },
    }