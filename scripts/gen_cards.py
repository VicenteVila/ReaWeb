#!/usr/bin/env python3
"""Genera y renderiza las tarjetas didácticas de ReaWeb.

Las tarjetas se definen como HTML/CSS (texto fluido, sin solapamientos) en
Docs/cards/cardN_src.html y se exportan a PNG con Chrome headless:

  Tarjeta 1 (reaweb_agente_y_arnes.png):  el LLM (esfera-ojo) envuelto por el arnés.
  Tarjeta 2 (reaweb_flujo_end_to_end.png): el flujo de trabajo con decisiones y bucles.

Uso:
  python -m scripts.gen_cards           # regenera PNG desde las fuentes HTML
"""

import shutil
import subprocess
from pathlib import Path

from tools.domain.visual_critic import find_chrome

CARDS = Path(__file__).resolve().parent.parent / "Docs" / "cards"
CARD_W, CARD_H = 1080, 1350

_SOURCES = {
    "reaweb_agente_y_arnes": "card1_src.html",
    "reaweb_flujo_end_to_end": "card2_src.html",
}


def verify_layout(src: Path, size: str = "1080,1350") -> tuple[bool, str]:
    """Reabre la fuente en Chrome headless y comprueba que el script VERIFY:
    embebido reporte OK (sin solapamientos, sin elementos fuera del viewport,
    sin overflow). Retorna (ok, mensaje)."""
    chrome = find_chrome()
    if not chrome:
        return False, "chrome no disponible"
    try:
        if Path("/usr/bin/wslpath").exists():
            win = lambda p: subprocess.run(["wslpath", "-w", str(p)],
                                           capture_output=True, text=True).stdout.strip()
        else:
            win = lambda p: str(p).replace("/mnt/c/", "C:\\").replace("/", "\\")
        cmd = [chrome, "--headless=new", "--disable-gpu",
               f"--window-size={size}", "--dump-dom", "file://" + win(src)]
        out = subprocess.run(cmd, capture_output=True, timeout=90)
        dom = out.stdout.decode("utf-8", errors="replace")
        m = None
        for m in __import__("re").finditer(r"<title>VERIFY:([^<]*)</title>", dom):
            pass
        if not m:
            return False, "sin reporte VERIFY en el DOM"
        msg = m.group(1)
        return msg.startswith("OK"), msg
    except Exception as e:
        return False, str(e)


def render_src_to_png(src: Path, png: Path) -> bool:
    chrome = find_chrome()
    if not chrome:
        return False
    try:
        if Path("/usr/bin/wslpath").exists():
            win = lambda p: subprocess.run(["wslpath", "-w", str(p)],
                                           capture_output=True, text=True).stdout.strip()
        else:
            win = lambda p: str(p).replace("/mnt/c/", "C:\\").replace("/", "\\")
        cmd = [
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--window-size={CARD_W},{CARD_H}",
            "--screenshot=" + win(png),
            "file://" + win(src),
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        return png.exists() and png.stat().st_size > 10000
    except Exception:
        return False


def main():
    CARDS.mkdir(parents=True, exist_ok=True)
    ok = True
    for png_name, src_name in _SOURCES.items():
        src = CARDS / src_name
        png = CARDS / (png_name + ".png")
        if not src.exists():
            print(f"[skip] fuente ausente: {src}")
            continue
        vok, vmsg = verify_layout(src)
        if not vok:
            ok = False
            print(f"[VERIFY FAIL] {png_name}: {vmsg}")
            continue
        print(f"[verify] {png_name}: {vmsg}")
        if render_src_to_png(src, png):
            print(f"[ok] {png.name} ({png.stat().st_size//1024} KB)")
        else:
            ok = False
            print(f"[FAIL] no se pudo renderizar {png.name} (Chrome disponible?)")
    print("listo" if ok else "con errores")


if __name__ == "__main__":
    main()
