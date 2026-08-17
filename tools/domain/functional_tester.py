"""Pruebas funcionales ejecutables (anti-trampa).

Renderiza el index.html de un candidato en Chrome headless con un runner de
tests inyectado: hace clicks reales sobre los elementos interactivos, dispara
submits de formularios, verifica que los enlaces internos apunten a elementos
existentes y captura errores JS. Reporta un score funcional 0-100.

Así el evaluador NO depende solo de checks estáticos (strings presentes):
una página que "parece" correcta pero cuyo JS está roto, cuyos botones no
reaccionan o cuyos formularios recargan la página falla aquí.
"""

import json
import re
import subprocess
from pathlib import Path

from tools.domain.visual_critic import find_chrome

# El runner se inyecta justo antes de </body>. Deja los resultados en
# document.title con prefijo "FUNC:" para leerlos con --dump-dom.
FUNC_RUNNER = r"""
<script>
(function(){
  if (window.__funcResults) return;
  window.__funcResults = {tests: [], errors: []};
  function rec(n,p,d){ window.__funcResults.tests.push({n:n,p:p?1:0,d:d||''}); }
  function done(){ document.title = 'FUNC:' + JSON.stringify(window.__funcResults); }

  var jsErrors = [];
  window.addEventListener('error', function(e){
    jsErrors.push(String(e.message).slice(0,120));
    window.__funcResults.errors.push(String(e.message).slice(0,120));
  });
  window.addEventListener('unhandledrejection', function(e){
    var msg = e && e.reason ? String(e.reason) : 'promise';
    jsErrors.push(msg.slice(0,120));
    window.__funcResults.errors.push(msg.slice(0,120));
  });

  function hrefExists(a){
    var id = a.getAttribute('href');
    if (id && id.charAt(0) === '#') {
      var target = document.getElementById(id.slice(1));
      return !!target;
    }
    return true;
  }

  function run(){
    var tests = [];
    var links = Array.prototype.slice.call(document.querySelectorAll('a[href^="#"]'));
    var broken = links.filter(function(a){ return !hrefExists(a); });
    rec('nav_links_validos', broken.length === 0,
        broken.length ? 'targets rotos: ' + broken.map(function(a){return a.getAttribute('href');}).slice(0,5).join(',')
                      : links.length + ' anclas OK');

    var buttons = Array.prototype.slice.call(document.querySelectorAll('button, a[role="button"], [role="button"]'));
    var btnErrors = 0;
    buttons.forEach(function(b){
      try { b.click(); }
      catch(e){ btnErrors++; window.__funcResults.errors.push('click:' + String(e).slice(0,80)); }
    });
    rec('botones_click_sin_error', btnErrors === 0,
        btnErrors ? btnErrors + ' botones lanzaron excepción' : buttons.length + ' botones OK');

    var forms = Array.prototype.slice.call(document.querySelectorAll('form'));
    var formOk = 0, formTot = 0;
    forms.forEach(function(f){
      formTot++;
      var captured = false;
      var probe = function(e){ e.preventDefault(); captured = true; };
      try { f.addEventListener('submit', probe); f.dispatchEvent(new Event('submit', {cancelable:true})); }
      catch(e){ window.__funcResults.errors.push('form:' + String(e).slice(0,80)); }
      if (captured) { formOk++; }
    });
    rec('formularios_no_recargan', formTot === 0 || formOk === formTot,
        formTot ? formOk + '/' + formTot + ' capturan submit' : 'sin form');

    // Interactividad real: los elementos interactivos DEBEN cambiar el DOM
    // al hacer click (filtro que refiltra, menú que abre, acordeón que despliega).
    // Si ningún click produce cambio observable, la página está "trampeada".
    var interactive = document.querySelectorAll(
      '[data-toggle], [aria-expanded], details, .accordion, [data-accordion], ' +
      '.menu-btn, .hamburger, [data-category], .filter, .filter-btn, .tab, ' +
      '[data-tab], [role="tab"], button, a[role="button"]'
    );
    var before = document.body.innerHTML;
    var reacted = 0;
    interactive.forEach(function(el){
      try {
        el.click();
      } catch(e){}
    });
    setTimeout(function(){
      var after = document.body.innerHTML;
      if (after !== before) reacted = 1;
      rec('interactivos_responden', interactive.length === 0 || reacted === 1,
          reacted ? 'el DOM cambió tras los clicks' : interactive.length + ' interactivos sin efecto');
      finish();
    }, 250);

    rec('js_sin_errores', jsErrors.length === 0,
        jsErrors.length ? jsErrors.join(' | ') : 'sin errores JS');

    function finish(){
      var passed = window.__funcResults.tests.filter(function(t){return t.p===1;}).length;
      var total = window.__funcResults.tests.length;
      var score = total ? Math.round(100 * passed / total) : 100;
      if (jsErrors.length) score = Math.max(score - 20, 0);
      // Interactividad sin efecto = síntoma de página trampa: castiga el doble.
      var ir = window.__funcResults.tests.filter(function(t){return t.n==='interactivos_responden';})[0];
      if (ir && ir.p === 0 && /sin efecto/.test(ir.d)) {
        score = Math.max(score - 20, 0);
      }
      window.__funcResults.score = score;
      done();
    }
  }

  if (document.readyState === 'complete') { run(); }
  else { window.addEventListener('load', run); }
})();
</script>
"""


def run_functional_test(html_path: Path, timeout: int = 60) -> dict:
    """Ejecuta las pruebas funcionales reales contra el HTML dado.

    Devuelve {"functional": 0-100, "tests": [...], "errors": [...], "ok": bool}.
    Si Chrome no está disponible devuelve {"functional": None, "ok": False}
    (sin penalizar: el gate solo aplica cuando el runner pudo ejecutarse).
    """
    chrome = find_chrome()
    if not chrome:
        return {"functional": None, "ok": False, "tests": [], "errors": ["chrome no disponible"]}

    html_path = Path(html_path)
    html = html_path.read_text(errors="replace")
    injected = html.replace("</body>", FUNC_RUNNER + "\n</body>", 1)
    if "</body>" not in html:
        injected = html + FUNC_RUNNER

    # El HTML inyectado se escribe en el MISMO directorio del candidato para que
    # las rutas relativas (src="app.js", href="styles.css") sigan resolviéndose.
    # Un nombre con sufijo .func.html evita colisionar con el index.html original.
    out_path = html_path.with_name(html_path.stem + ".func.html")
    try:
        out_path.write_text(injected, encoding="utf-8")
        try:
            if Path("/usr/bin/wslpath").exists():
                win = subprocess.run(["wslpath", "-w", str(out_path)],
                                     capture_output=True, text=True).stdout.strip()
            else:
                win = str(out_path).replace("/mnt/c/", "C:\\").replace("/", "\\")
        except OSError:
            win = str(out_path).replace("/mnt/c/", "C:\\").replace("/", "\\")

        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--virtual-time-budget=6000",
            "--dump-dom",
            "file://" + win,
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except Exception as e:
            return {"functional": None, "ok": False,
                    "tests": [], "errors": [f"chrome ejecucion: {e}"]}

        dom = out.stdout.decode("utf-8", errors="replace")
        m = re.search(r"<title>FUNC:(\{.*?\})</title>", dom, re.S)
        if not m:
            return {"functional": None, "ok": False,
                    "tests": [], "errors": ["runner no reportó (FUNC: ausente en DOM)"]}
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            return {"functional": None, "ok": False,
                    "tests": [], "errors": ["runner reportó JSON inválido"]}
    finally:
        if out_path.exists():
            try:
                out_path.unlink()
            except OSError:
                pass

    return {
        "functional": data.get("score"),
        "tests": data.get("tests", []),
        "errors": data.get("errors", []),
        "ok": True,
    }