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
  // Tests P0: su fallo capa el score aunque la media sea alta. Deben declararse
  // aquí Y en FUNCTIONAL_TESTS (Python); el post-check de run_functional_test
  // avisa si alguno se quedó sin ejecutar.
  var P0_TESTS = ['js_sin_errores', 'interactivos_responden', 'grafo_visible'];
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
      checkGrafo();
      finish();
    }, 250);

    rec('js_sin_errores', jsErrors.length === 0,
        jsErrors.length ? jsErrors.join(' | ') : 'sin errores JS');

    // Punto 12c: el SVG de contenido DEBE dibujarse. Se mide DESPUÉS de que
    // resuelvan los fetch() del runtime (dentro del setTimeout), porque el JS
    // que dibuja el grafo es asíncrono: medir de forma síncrona reportaba 0
    // nodos en páginas que sí dibujaban. Se elige por id conocido o, si no, el
    // <svg> dentro de un contenedor de grafo o el de más hijos.
    // Señal primaria = nodos (circles) dibujados; las aristas (lines) son
    // informativas, porque hay implementaciones que solo las dibujan al hover.
    function checkGrafo(){
      var svgs = Array.prototype.slice.call(document.querySelectorAll('svg'));
      var ksvg = document.getElementById('knowledge-svg')
               || document.getElementById('main-svg')
               || svgs.filter(function(s){
                    return s.closest('#graph, .graph-container, .graph');
                  })[0]
               || svgs.slice().sort(function(a,b){
                    return b.childElementCount - a.childElementCount;
                  })[0];
      if (!ksvg) return;
      var circles = ksvg.querySelectorAll('circle');
      var lines = ksvg.querySelectorAll('line');
      var texts = ksvg.querySelectorAll('text');
      if (circles.length >= 3) {
        rec('grafo_visible', 1,
            circles.length + ' nodos, ' + lines.length + ' edges, ' + texts.length + ' textos');
      } else {
        rec('grafo_visible', 0,
            'SVG declarado pero sin grafo (' + circles.length + ' circles): el JS ' +
            'que lo dibuja no se ejecutó (¿fetch falló?)');
      }
    }

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
      // Cualquier test P0 fallado capa el score aunque la media pase: una media
      // alta no puede tapar "el grafo no se dibuja" o "el JS está roto".
      var p0 = window.__funcResults.tests.filter(function(t){
        return t.p === 0 && P0_TESTS.indexOf(t.n) >= 0;
      });
      if (p0.length) score = Math.min(score, 59);
      window.__funcResults.score = score;
      done();
    }
  }

  if (document.readyState === 'complete') { run(); }
  else { window.addEventListener('load', run); }
})();
</script>
"""


# Manifiesto de tests funcionales que el runner DEBE reportar. Si alguno no
# aparece en los resultados, el runner tiene un bug (o el JS no corrió) y el
# harness debe saberlo en vez de puntuar sobre un subconjunto silencioso: así
# una media alta no puede tapar que "el grafo no se dibujó" porque el test ni
# siquiera se ejecutó. `grafo_visible` es condicional por diseño (solo hay SVG
# en algunas páginas), por eso se marca como opcional: si no hay SVG, el test
# no aplica y no penaliza.
FUNCTIONAL_TESTS = [
    ("nav_links_validos", True),
    ("botones_click_sin_error", True),
    ("formularios_no_recargan", True),
    ("js_sin_errores", True),
    ("interactivos_responden", True),
    ("grafo_visible", False),
]

# Tests cuyo fallo individual capa el score funcional aunque la media pase.
P0_TESTS = ["js_sin_errores", "interactivos_responden", "grafo_visible"]


def missing_required_tests(tests: list) -> list[str]:
    """Tests obligatorios del manifiesto que el runner no reportó."""
    got = {t.get("n") for t in (tests or [])}
    return [n for n, required in FUNCTIONAL_TESTS if required and n not in got]


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
        from tools.domain.render_server import page_url

        url, extra, stop = page_url(out_path, project_dir=html_path.parent)

        cmd = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--virtual-time-budget=6000",
            "--dump-dom",
            *extra,
            url,
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except Exception as e:
            return {"functional": None, "ok": False,
                    "tests": [], "errors": [f"chrome ejecucion: {e}"]}
        finally:
            stop()

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

    missing = missing_required_tests(data.get("tests", []))
    errors = list(data.get("errors", []))
    if missing:
        # El runner no ejecutó un test obligatorio: es un fallo del harness, no
        # de la página. No se penaliza el score (puede ser una página sin esos
        # elementos), pero queda registrado para que no pase inadvertido.
        errors.append(
            "runner no ejecutó tests obligatorios: " + ", ".join(missing)
        )

    return {
        "functional": data.get("score"),
        "tests": data.get("tests", []),
        "errors": errors,
        "missing_required": missing,
        "ok": True,
    }