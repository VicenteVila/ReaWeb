"""Servidor HTTP local efímero para renderizar y testear candidatos.

Por qué existe (bug corregido en scoring v2): el harness renderizaba y testeaba
los candidatos con `file://`, donde el origen es `null` y **cualquier `fetch()`
a un recurso local está bloqueado por CORS**. El código generado por el agente
usa `fetch('repos.json')` / `fetch('flujogramas/...')`, así que bajo `file://`
el JS nunca completaba: `initGraph()` no se llamaba, el SVG quedaba vacío y el
crítico VLM puntuaba "área del grafo completamente vacía" en todas las
hipótesis. Peor: la web *sí* funcionaba al publicarla por HTTP, así que el
entorno de medición no representaba la realidad.

Sirviendo por `http://127.0.0.1` el render y los tests funcionales miden lo
mismo que verá el usuario. `127.0.0.1` (y no otra IP) porque el Chrome que se
invoca es de Windows y necesita alcanzar el servidor que vive en WSL.

Uso:

    with serve_dir(project_dir) as base_url:
        url = base_url + "/index.html"

Si el servidor no puede arrancarse, `base_url` es `None` y el llamador debe
caer al modo `file://` con `--allow-file-access-from-files` (ver
`file_url_for` / `ALLOW_FILE_ACCESS_FLAG`): es peor que HTTP, pero es
infinito mejor que medir en un runtime que rompe la página.
"""
from __future__ import annotations

import contextlib
import functools
import http.server
import socket
import socketserver
import threading
from pathlib import Path

# Flag que permite a Chrome leer recursos locales desde file:// (origen null).
# Solo se usa como fallback cuando no hay servidor HTTP disponible.
ALLOW_FILE_ACCESS_FLAG = "--allow-file-access-from-files"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler sin logueo a stderr (el harness es silencioso)."""

    def log_message(self, fmt, *args):  # noqa: A003 - firma de la stdlib
        pass


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


@contextlib.contextmanager
def serve_dir(directory: str | Path, timeout: float = 10.0):
    """Sirve `directory` en http://<ip-wsl>:<puerto> mientras dura el contexto.

    Cede (base_url, None) si no se puede arrancar el servidor, para que el
    llamador degrade a `file://` en vez de romper la renderización.
    """
    directory = Path(directory)
    if not directory.is_dir():
        yield None, None
        return

    handler = functools.partial(_QuietHandler, directory=str(directory))
    # Escucha en 0.0.0.0 (NO 127.0.0.1): el Chrome que invoca el harness es una
    # app de Windows y necesita alcanzar el servidor que vive en WSL. Con
    # 127.0.0.1 el puerto queda ligado al loopback de WSL y Windows recibe
    # "connection refused" (página de error, no la web). 0.0.0.0 es seguro aquí
    # porque el servidor es efímero, escucha en un puerto alto aleatorio y
    # solo vive durante el render.
    try:
        server = _ReusableTCPServer(("0.0.0.0", 0), handler)
    except OSError:
        yield None, None
        return

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        base = _base_url_for_windows(port)
        yield base, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=timeout)


def _wsl_ip() -> str | None:
    """IP IPv4 de la interfaz principal en WSL (para que Windows la alcance)."""
    import subprocess

    try:
        out = subprocess.run(
            ["sh", "-c",
             "ip -4 addr show eth0 2>/dev/null | grep -oP '(?<=inet )[0-9.]+' "
             "|| hostname -I 2>/dev/null | awk '{print $1}'"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("127."):
            return line
    return None


def _base_url_for_windows(port: int) -> str:
    """URL base alcanzable desde el Chrome de Windows.

    Prefiere la IP de WSL; si no se puede determinar, cae a 127.0.0.1 (que sí
    funciona si el harness corre en Windows nativo, no en WSL).
    """
    ip = _wsl_ip()
    return f"http://{ip}:{port}" if ip else f"http://127.0.0.1:{port}"


def file_url_for(html_path: str | Path) -> str:
    """URL file:// para Chrome de Windows (WSL), con wslpath si está disponible."""
    import subprocess

    html_path = Path(html_path).resolve()
    try:
        if Path("/usr/bin/wslpath").exists():
            win = subprocess.run(
                ["wslpath", "-w", str(html_path)],
                capture_output=True, text=True,
            ).stdout.strip()
        else:
            raise OSError
    except OSError:
        win = str(html_path).replace("/mnt/c/", "C:\\").replace("/", "\\")
    if not win:
        win = str(html_path).replace("/mnt/c/", "C:\\").replace("/", "\\")
    return "file://" + win


def win_path(p: str | Path) -> str:
    """Convierte una ruta WSL a formato Windows (para --screenshot=...)."""
    import subprocess

    p = Path(p)
    try:
        if Path("/usr/bin/wslpath").exists():
            out = subprocess.run(
                ["wslpath", "-w", str(p.resolve())],
                capture_output=True, text=True,
            ).stdout.strip()
            if out:
                return out
    except OSError:
        pass
    return str(p).replace("/mnt/c/", "C:\\").replace("/", "\\")


def page_url(html_path: str | Path, project_dir: str | Path | None = None,
             allow_file_fallback: bool = True):
    """URL para cargar una página desde Chrome, prefiriendo HTTP sobre file://.

    Devuelve (url, extra_flags). `extra_flags` incluye
    `--allow-file-access-from-files` **solo** en el fallback a `file://`, para
    que el JS con `fetch()` tenga una oportunidad de funcionar.

    IMPORTANTE: el servidor debe seguir vivo mientras Chrome carga la página.
    Por eso el contexto se cierra explícitamente con `stop()`. Si el llamador
    olvida `stop()`, el servidor de termina al recoger el objeto y Chrome verá
    una página de error:

        url, extra, stop = page_url(index_html)
        try:
            subprocess.run([chrome, ..., url])
        finally:
            stop()
    """
    html_path = Path(html_path)
    root = Path(project_dir) if project_dir else html_path.parent

    ctx = serve_dir(root)
    base_url, _server = ctx.__enter__()
    if base_url:
        def stop(_ctx=ctx):
            _ctx.__exit__(None, None, None)
        return base_url + "/" + html_path.name, [], stop

    ctx.__exit__(None, None, None)
    if allow_file_fallback:
        return file_url_for(html_path), [ALLOW_FILE_ACCESS_FLAG], lambda: None
    return file_url_for(html_path), [], lambda: None


def free_port_available(port: int = 0) -> bool:
    """Utilidad de diagnóstico: ¿hay un puerto libre para servir?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
