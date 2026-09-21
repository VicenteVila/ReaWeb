/* particles.js - Fondo "escritorio neon": particulas neurales conectadas
 * + 4 ventanas animadas SIN marcos (codigo Python, graficas, flujograma
 * inventado, terminal/logs) en colores distintivos pero muy tenues.
 *
 * Un unico <canvas> fijo detras del contenido. Pausa al hacer scroll fuera del
 * grafo, al ocultar la pestana, en modo reduced-motion y simplifica en movil.
 * Lee colores de variables CSS (--particle/--link y --win-*).
 */
(function () {
  'use strict';
  if (!document || typeof window === 'undefined' || !window.requestAnimationFrame) {
    return;
  }

  var reduced = false;
  var mq = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  if (mq) {
    reduced = mq.matches;
    if (mq.addEventListener) {
      mq.addEventListener('change', function () { reduced = mq.matches; });
    }
  }

  var canvas = document.getElementById('neural-bg');
  if (!canvas) {
    canvas = document.createElement('canvas');
    canvas.id = 'neural-bg';
    canvas.setAttribute('aria-hidden', 'true');
    document.body.insertBefore(canvas, document.body.firstChild);
  }

  var ctx = canvas.getContext('2d');
  var W = 0, H = 0, dpr = 1;
  var particles = [];
  var mouse = { x: -9999, y: -9999, active: false };
  var running = false;
  var rafId = null;
  var animT = 0;
  var lastNow = 0;
  var scrollPaused = false;

  var COUNT_MOBILE = 40;
  var COUNT_DESKTOP = 80;
  var MAX_DIST = 130;
  var MOUSE_DIST = 160;

  // ----- utilidades canvas -----
  function rrectPath(x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function text(str, x, y, color, alpha, font, align) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.font = font || '11px Consolas, Menlo, monospace';
    ctx.textAlign = align || 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(str, x, y);
  }

  // Paletas tenues de texto por ventana
  var PAL = {
    py: { base: '#9ae8c8', kw: '#34d399', str: '#6ee7b7', com: '#2f8f6b', num: '#a7f3d0' },
    ch: { base: '#c4b5fd', kw: '#a78bfa', str: '#ddd6fe', com: '#6d5aa8', num: '#e9d5ff' },
    fl: { base: '#bae6fd', kw: '#38bdf8', str: '#7dd3fc', com: '#4c86bf', num: '#bfdbfe' },
    tm: { base: '#fde68a', kw: '#fbbf24', str: '#fef3c7', com: '#a3711f', num: '#fde68a' }
  };
  // alpha global muy tenue para contenido de windows
  var WIN_ALPHA = 0.42;

  function readColors() {
    var cs = getComputedStyle(document.body);
    var dark = document.body.classList.contains('dark-theme');
    function v(n, f) { return cs.getPropertyValue(n).trim() || f; }
    return {
      dark: dark,
      pt: v('--particle', dark ? 'rgba(34,211,238,0.85)' : 'rgba(99,102,241,0.65)'),
      link: v('--link', dark ? 'rgba(167,139,250,0.75)' : 'rgba(99,102,241,0.40)'),
      linkDim: v('--link-dim', dark ? 'rgba(34,211,238,0.35)' : 'rgba(99,102,241,0.20)'),
      py: v('--win-python', dark ? 'rgba(52,211,153,0.40)' : 'rgba(16,185,129,0.30)'),
      ch: v('--win-chart', dark ? 'rgba(167,139,250,0.40)' : 'rgba(129,90,239,0.30)'),
      fl: v('--win-flow', dark ? 'rgba(56,189,248,0.40)' : 'rgba(56,130,246,0.30)'),
      tm: v('--win-term', dark ? 'rgba(251,191,36,0.36)' : 'rgba(217,156,20,0.28)')
    };
  }

  // ---------- WINDOWS: codigo python ----------
  var PY_SCRIPT = [
    "import asyncio, json",
    "from core.agent import Agent",
    "",
    "class ResearchAgent(Agent):",
    "    async def run(self, prompt):",
    "        # planificar el flujo de trabajo",
    "        plan = self.plan(prompt)",
    "        tasks = [self.execute(t) for t in plan]",
    "        results = await asyncio.gather(*tasks)",
    "        return self.synthesize(results)",
    "",
    "def main():",
    "    agent = ResearchAgent('sci-fi')",
    "    out = asyncio.run(agent.run('explore'))",
    "    print(out.summary)",
    "    agent.record_skill(out)",
    "",
    "if __name__ == '__main__':",
    "    main()"
  ];
  var PY_NCHARS = 0;
  PY_SCRIPT.forEach(function (l) { PY_NCHARS += l.length + 1; });
  var PY_CYCLE = 26, PY_REVEAL = 20;

  function paintCodeTokens(line, x, y, pal, lh) {
    // mini resaltador de sintaxis
    var re = /(#.*$)|("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|\b(def|class|import|from|as|return|for|in|if|else|while|async|await|print|self|None|True|False|lambda|with|try|except|pass|yield|not)\b|(\b\d+(?:\.\d+)?\b)|(\w+)|\s+/g;
    var m, cx = x;
    while ((m = re.exec(line)) !== null) {
      var col = pal.base;
      if (m[1]) col = pal.com;
      else if (m[2]) col = pal.str;
      else if (m[3]) col = pal.kw;
      else if (m[4]) col = pal.num;
      text(m[0], cx, y, col, WIN_ALPHA, lh, 'left');
      var wpx = ctx.measureText(m[0]).width;
      cx += wpx;
    }
  }

  function drawPython(rect, t, pal) {
    var x = rect.x, y = rect.y, w = rect.w, h = rect.h, lh = Math.max(14, Math.floor(h / 15));
    var font = lh + 'px Consolas, Menlo, monospace';
    // progreso de revelado
    var p = (t % PY_CYCLE) / PY_CYCLE;
    var restNorm = PY_REVEAL / PY_CYCLE;
    var chars, caretOn;
    if (p >= restNorm) {
      chars = PY_NCHARS;                       // todo revelado (fase de pausa)
      caretOn = (Math.floor(t * 2) % 2 === 0);
    } else {
      chars = Math.floor((p / restNorm) * PY_NCHARS);
      caretOn = true;
    }
    text('· agent.py', x, y + lh, pal.kw, WIN_ALPHA, font);
    var cy = y + lh * 2.2;
    var remaining = chars, rowIndex = 0;
    for (var i = 0; i < PY_SCRIPT.length; i++) {
      var line = PY_SCRIPT[i];
      if (cy > rect.y + rect.h) break;
      var budget = line.length + 1;
      if (remaining <= 0) break;              // nada mas que revelar
      if (remaining >= budget) {
        paintCodeTokens(line, x, cy, pal, font);
        remaining -= budget;
      } else if (remaining > 0) {
        var part = line.slice(0, remaining);
        paintCodeTokens(part, x, cy, pal, font);
        // cursor
        if (caretOn) {
          var cw = ctx.measureText(part).width;
          text('▎', x + cw + 1, cy, pal.kw, WIN_ALPHA + 0.2, font);
        }
        remaining = 0;
      }
      cy += lh;
      rowIndex++;
    }
  }

  // ---------- WINDOWS: graficas ----------
  function drawCharts(rect, t, col) {
    var x = rect.x, y = rect.y, w = rect.w, h = rect.h;
    var gx = x + 4;
    // 1) barras
    var bw = (w * 0.48), bx = gx, by = y + 6, bh = h * 0.42;
    var bars = 6, gap = 4, barw = (bw - gap * (bars - 1)) / bars;
    for (var i = 0; i < bars; i++) {
      var v = 0.28 + 0.62 * (0.5 + 0.5 * Math.sin(t * 1.2 + i * 0.9));
      var hh = v * bh;
      var bx0 = bx + i * (barw + gap);
      ctx.globalAlpha = WIN_ALPHA;
      ctx.fillStyle = col;
      rrectPath(bx0, by + bh - hh, barw, hh, 2);
      ctx.fill();
    }
    // 2) area/linea
    var ax = x + w * 0.52, ay = y + 6, aw = w * 0.46, ah = h * 0.42;
    ctx.globalAlpha = WIN_ALPHA * 0.5;
    ctx.strokeStyle = col;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    var pts = [];
    for (var k = 0; k <= 24; k++) {
      var px = ax + (k / 24) * aw;
      var pyv = ay + ah * 0.5 - Math.sin(k / 24 * Math.PI * 2 + t * 1.5) * ah * 0.34
        - Math.sin(k / 24 * Math.PI * 6 + t * 0.7) * ah * 0.12;
      if (k === 0) ctx.moveTo(px, pyv); else ctx.lineTo(px, pyv);
      pts.push([px, pyv]);
    }
    ctx.stroke();
    // area bajo la linea
    ctx.globalAlpha = WIN_ALPHA * 0.12;
    ctx.fillStyle = col;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], ay + ah);
    pts.forEach(function (p) { ctx.lineTo(p[0], p[1]); });
    ctx.lineTo(pts[pts.length - 1][0], ay + ah);
    ctx.closePath();
    ctx.fill();
    // 3) donut
    var dx = x + w * 0.20, dy = y + h * 0.78, dr = Math.min(w * 0.18, h * 0.20);
    var frac = 0.35 + 0.45 * (0.5 + 0.5 * Math.sin(t * 0.7));
    ctx.globalAlpha = WIN_ALPHA;
    ctx.strokeStyle = col;
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.arc(dx, dy, dr, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frac);
    ctx.stroke();
    ctx.globalAlpha = WIN_ALPHA * 0.25;
    ctx.beginPath();
    ctx.arc(dx, dy, dr, 0, Math.PI * 2);
    ctx.stroke();
  }

  // ---------- WINDOWS: flujograma inventado ----------
  var FL_NODES = [
    { fx: 0.10, fy: 0.16, label: 'config' },
    { fx: 0.42, fy: 0.16, label: 'load' },
    { fx: 0.74, fy: 0.16, label: 'validate' },
    { fx: 0.26, fy: 0.52, label: 'train' },
    { fx: 0.60, fy: 0.52, label: 'evaluate' },
    { fx: 0.88, fy: 0.52, label: 'ship' },
    { fx: 0.45, fy: 0.84, label: 'deploy' }
  ];
  var FL_EDGES = [[0, 1], [1, 2], [1, 3], [3, 4], [2, 4], [4, 5], [5, 6]];
  var FL_CYCLE = 16, FL_REVEAL = 12;

  function drawFlow(rect, t, col) {
    var x = rect.x, y = rect.y, w = rect.w, h = rect.h;
    var p = (t % FL_CYCLE) / FL_CYCLE;
    var rev = Math.min(1, p / (FL_REVEAL / FL_CYCLE));
    var nShown = Math.floor(rev * FL_NODES.length);
    var pts = FL_NODES.map(function (n) {
      return { px: x + n.fx * w, py: y + n.fy * h, label: n.label };
    });
    // aristas (aparecen cuando ambos extremos visibles)
    ctx.globalAlpha = WIN_ALPHA * 0.7;
    ctx.strokeStyle = col;
    ctx.lineWidth = 1.1;
    FL_EDGES.forEach(function (e) {
      if (e[0] < nShown && e[1] < nShown) {
        var a = pts[e[0]], b = pts[e[1]];
        ctx.beginPath();
        ctx.moveTo(a.px, a.py);
        ctx.lineTo(b.px, b.py);
        ctx.stroke();
        // small arrowhead
        var ang = Math.atan2(b.py - a.py, b.px - a.px);
        ctx.beginPath();
        ctx.moveTo(b.px, b.py);
        ctx.lineTo(b.px - 7 * Math.cos(ang - 0.4), b.py - 7 * Math.sin(ang - 0.4));
        ctx.lineTo(b.px - 7 * Math.cos(ang + 0.4), b.py - 7 * Math.sin(ang + 0.4));
        ctx.closePath();
        ctx.fillStyle = col;
        ctx.globalAlpha = WIN_ALPHA * 0.7;
        ctx.fill();
      }
    });
    // nodos
    pts.forEach(function (pt, i) {
      var vis = i < nShown;
      var glow = 0;
      if (vis) glow = (0.5 + 0.5 * Math.sin(t * 3 + i));   // pulso
      var nw = Math.min(w * 0.20, 64), nh = Math.min(h * 0.20, 22);
      if (vis) {
        ctx.globalAlpha = WIN_ALPHA * (0.5 + glow * 0.5);
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.2;
        rrectPath(pt.px - nw / 2, pt.py - nh / 2, nw, nh, 5);
        ctx.stroke();
        ctx.globalAlpha = WIN_ALPHA * 0.10;
        rrectPath(pt.px - nw / 2, pt.py - nh / 2, nw, nh, 5);
        ctx.fill();
        text(pt.label, pt.px + 6, pt.py + 3, col, WIN_ALPHA * 0.9, Math.max(10, nh * 0.62) + 'px Consolas, monospace', 'left');
      }
    });
  }

  // ---------- WINDOWS: terminal/logs ----------
  var TERM_LOG = [
    {"s": "bootstrap", "k": "cmd"},
    {"s": "loading modules ... ok", "k": "ok"},
    {"s": "agent.skill engine v3.2", "k": "info"},
    {"s": "connecting to graph-core", "k": "info"},
    {"s": "handshake: 128ms latency", "k": "dim"},
    {"s": "spawning 4 worker nodes", "k": "ok"},
    {"s": "worker[0] status: ready", "k": "dim"},
    {"s": "worker[1] status: ready", "k": "dim"},
    {"s": "worker[2] status: ready", "k": "dim"},
    {"s": "worker[3] status: ready", "k": "dim"},
    {"s": "indexing knowledge graph", "k": "info"},
    {"s": "sync: 5.4k embeddings", "k": "ok"}
  ];
  var TERM_CYCLE = 14;

  function drawTerminal(rect, t, pal) {
    var x = rect.x, y = rect.y, w = rect.w, h = rect.h, lh = Math.max(15, Math.floor(h / 12));
    var font = lh + 'px Consolas, Menlo, monospace';
    var p = (t % TERM_CYCLE) / TERM_CYCLE;
    // scroll: desplaza las lineas hacia arriba continuamente
    var offset = Math.floor(p * TERM_LOG.length);
    var visible = Math.min(TERM_LOG.length, Math.floor(h / lh) - 1);
    for (var i = 0; i < visible; i++) {
      var idx = (offset + i) % TERM_LOG.length;
      var it = TERM_LOG[idx];
      var col = pal.base;
      if (it.k === 'cmd') col = pal.kw;
      else if (it.k === 'ok') col = pal.str;
      else if (it.k === 'dim') col = pal.com;
      var prefix = it.k === 'cmd' ? '$ ' : '  ';
      text(prefix + it.s, x, y + lh * (i + 1.2), col, WIN_ALPHA, font);
    }
    // barra de progreso
    var pb = 0.5 + 0.5 * Math.sin(t * 0.6);
    var pby = y + h - 8, pbw = w * 0.9, pbx = x + 4;
    ctx.globalAlpha = WIN_ALPHA * 0.15;
    ctx.fillStyle = pal.base;
    rrectPath(pbx, pby - 3, pbw, 5, 3);
    ctx.fill();
    ctx.globalAlpha = WIN_ALPHA * 0.8;
    ctx.fillStyle = pal.kw;
    rrectPath(pbx, pby - 3, pbw * pb, 5, 3);
    ctx.fill();
    text('index ' + Math.floor(pb * 100) + '%', pbx + pbw + 8, pby + 1, pal.base, WIN_ALPHA, font);
  }

  // ---------- compone las ventanas (layout sin marcos) ----------
  function windowsEnabled() { return W >= 800; }

  function drawWindows(t) {
    if (!windowsEnabled()) return;
    var pad = Math.max(14, W * 0.006);
    var top1 = H * 0.045, top2 = H * 0.42;
    var c = readColors();
    // Ventana A: python (sup-izq)   Ventana B: graficas (sup-der)
    var rA = { x: pad, y: top1, w: W * 0.46 - pad, h: H * 0.30 };
    var rB = { x: W * 0.52, y: top1, w: W * 0.47 - pad, h: H * 0.26 };
    // Ventana C: flujograma (inf-izq)   Ventana D: terminal (inf-der)
    var rC = { x: pad, y: top2 - 8, w: W * 0.54 - pad, h: H * 0.30 };
    var rD = { x: W * 0.56, y: top2 + 2, w: W * 0.43 - pad, h: H * 0.26 };
    drawPython(rA, t, PAL.py);
    drawCharts(rB, t, c.ch);
    drawFlow(rC, t, c.fl);
    drawTerminal(rD, t, PAL.tm);
  }

  function shouldAnimate() {
    return !reduced && !document.hidden && !scrollPaused;
  }

  // ---------- resize / spawn / particles ----------
  function resize() {
    var w = window.innerWidth, h = window.innerHeight;
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = w; H = h;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    spawn();
  }

  function spawn() {
    var count = W < 700 ? COUNT_MOBILE : COUNT_DESKTOP;
    var goal = count;
    if (reduced) goal = Math.min(goal, 20);
    while (particles.length < goal) particles.push(newParticle());
    if (particles.length > goal) particles.length = goal;
  }
  function newParticle() {
    return {
      x: Math.random() * W, y: Math.random() * H,
      r: Math.random() * 1.8 + 0.8,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35,
      phase: Math.random() * Math.PI * 2
    };
  }

  function drawParticles(c) {
    var n = particles.length, i, j;
    for (i = 0; i < n; i++) particles[i] = move(particles[i]);
    for (i = 0; i < n; i++) {
      var a = particles[i];
      for (j = i + 1; j < n; j++) {
        var b = particles[j];
        var dx = a.x - b.x, dy = a.y - b.y, d2 = dx * dx + dy * dy;
        if (d2 < MAX_DIST * MAX_DIST) {
          var d = Math.sqrt(d2);
          ctx.strokeStyle = c.link;
          ctx.globalAlpha = (1 - d / MAX_DIST) * 0.5;
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
    }
    ctx.globalAlpha = 1;
    for (i = 0; i < n; i++) {
      var p = particles[i];
      var glow = 0;
      if (mouse.active) {
        var mdx = p.x - mouse.x, mdy = p.y - mouse.y, md2 = mdx * mdx + mdy * mdy;
        if (md2 < MOUSE_DIST * MOUSE_DIST) glow = 1 - Math.sqrt(md2) / MOUSE_DIST;
      }
      ctx.globalAlpha = 0.6 + glow * 0.4;
      ctx.fillStyle = c.pt;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r + glow * 0.6, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  function move(p) {
    p.x += p.vx + Math.sin(p.phase) * 0.06;
    p.y += p.vy + Math.cos(p.phase * 1.3) * 0.06;
    p.phase += 0.004;
    if (p.x < -10) p.x = W + 10; else if (p.x > W + 10) p.x = -10;
    if (p.y < -10) p.y = H + 10; else if (p.y > H + 10) p.y = -10;
    return p;
  }

  function frame(t) {
    var c = readColors();
    ctx.clearRect(0, 0, W, H);
    drawWindows(t);
    drawParticles(c);
    ctx.globalAlpha = 1;
  }

  function staticFrame() {
    // en modo estatico usar un tiempo representativo (no 0) para que las
    // ventanas muestren contenido (revelado a medio camino del ciclo).
    frame(animT || 7.5);
  }

  // ---------- bucle ----------
  function tick(now) {
    if (!running) return;
    window.__bgFrameCount = (window.__bgFrameCount || 0) + 1;
    if (lastNow === 0) lastNow = now;
    var dt = Math.min(0.05, (now - lastNow) / 1000);
    lastNow = now;
    if (shouldAnimate()) animT += dt;
    frame(animT);
    rafId = window.requestAnimationFrame(tick);
  }
  function start() {
    if (running) return;
    running = true; lastNow = 0;
    rafId = window.requestAnimationFrame(tick);
  }
  function stop() {
    running = false;
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = null;
  }
  function applyMode() {
    resize();
    if (shouldAnimate()) start();
    else { stop(); staticFrame(); }
  }

  // ---------- eventos ----------
  window.addEventListener('resize', function () {
    resize();
    if (!shouldAnimate()) staticFrame();
  });
  window.addEventListener('mousemove', function (e) { mouse.x = e.clientX; mouse.y = e.clientY; mouse.active = true; });
  window.addEventListener('touchmove', function (e) { if (e.touches && e.touches.length) { mouse.x = e.touches[0].clientX; mouse.y = e.touches[0].clientY; mouse.active = true; } }, { passive: true });
  window.addEventListener('mouseleave', function () { mouse.active = false; });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop(); else applyMode();
  });

  // pausa al hacer scroll: cuando el grafo sale de viewport (solo landing)
  if (window.IntersectionObserver) {
    var target = document.getElementById('graph-viewport')
      || document.getElementById('main')
      || document.body;
    var io = new IntersectionObserver(function (entries) {
      var e = entries[0];
      scrollPaused = !e || (e.intersectionRatio < 0.03);
      applyMode();
    }, { threshold: [0, 0.03, 0.2] });
    if (target) io.observe(target);
    // re-evaluar al hacer scroll
    var scrollTimer = null;
    window.addEventListener('scroll', function () {
      if (scrollTimer) return;
      scrollTimer = setTimeout(function () {
        scrollTimer = null;
        if (!shouldAnimate()) staticFrame();
      }, 200);
    }, { passive: true });
  }

  // cambio de tema
  if (window.MutationObserver) {
    var obs = new MutationObserver(function () {
      if (!shouldAnimate()) staticFrame();
    });
    obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  applyMode();
})();
