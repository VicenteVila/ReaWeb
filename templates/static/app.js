// app.js — semilla con grafo de conocimiento dinámico (Punto 12c)
document.addEventListener('DOMContentLoaded', () => {
  // --- Form handler ---
  const form = document.querySelector('#contact-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const btn = form.querySelector('button');
      btn.textContent = 'Enviado con éxito';
      btn.style.background = '#22c55e';
      setTimeout(() => {
        btn.textContent = 'Enviar (Respuesta en 24h)';
        btn.style.background = 'var(--c-accent)';
        form.reset();
      }, 3000);
    });
  }

  // --- Card hover ---
  document.querySelectorAll('.card').forEach(card => {
    card.addEventListener('mouseenter', () => {
      card.style.borderColor = 'var(--c-accent)';
    });
    card.addEventListener('mouseleave', () => {
      card.style.borderColor = 'transparent';
    });
  });

  // --- Knowledge Graph (fetch dinámico desde graph_data.json) ---
  const svg = document.getElementById('knowledge-svg');
  if (svg) {
    fetch('graph_data.json')
      .then(r => r.json())
      .then(data => renderGraph(svg, data))
      .catch(() => {});
  }
});

// --- Grafo de conocimiento: renderiza SVG desde graph_data.json ---
function renderGraph(svg, data) {
  const repos = data.repos || [];
  if (!repos.length) return;

  const W = 800, H = 400;
  const CX = W / 2, CY = H / 2;
  const R_ORBIT = 150;
  const NS = 'http://www.w3.org/2000/svg';

  const TOPIC_COLORS = {
    'cs.AI': '#3B82F6', 'cs.SE': '#10B981', 'cs.CL': '#8B5CF6',
    'cs.MA': '#F59E0B', 'cs.CV': '#EF4444', 'cs.IR': '#06B6D4',
  };

  // Índice topic → repos
  const topicMap = {};
  repos.forEach(repo => {
    (repo.topics || []).forEach(t => {
      if (!topicMap[t.code]) topicMap[t.code] = [];
      topicMap[t.code].push(repo.name);
    });
  });

  // Calcular edges: repos que comparten topics
  const edges = [];
  repos.forEach((a, i) => {
    repos.forEach((b, j) => {
      if (j <= i) return;
      const aT = new Set((a.topics || []).map(t => t.code));
      const bT = new Set((b.topics || []).map(t => t.code));
      const shared = [...aT].filter(t => bT.has(t));
      if (shared.length) {
        edges.push({ from: a.name, to: b.name, shared, weight: shared.length });
      }
    });
  });

  // Posiciones: repos en círculo
  const pos = {};
  repos.forEach((repo, i) => {
    const angle = (2 * Math.PI * i) / repos.length - Math.PI / 2;
    pos[repo.name] = {
      x: CX + R_ORBIT * Math.cos(angle),
      y: CY + R_ORBIT * Math.sin(angle),
    };
  });

  svg.innerHTML = '';

  // Dibujar edges entre repos
  edges.forEach(e => {
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', pos[e.from].x);
    line.setAttribute('y1', pos[e.from].y);
    line.setAttribute('x2', pos[e.to].x);
    line.setAttribute('y2', pos[e.to].y);
    line.setAttribute('stroke', '#555');
    line.setAttribute('stroke-width', 1 + e.weight * 0.8);
    line.setAttribute('stroke-opacity', 0.4 + e.weight * 0.15);
    svg.appendChild(line);
  });

  // Dibujar edges desde centro a cada repo
  repos.forEach(repo => {
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', CX);
    line.setAttribute('y1', CY);
    line.setAttribute('x2', pos[repo.name].x);
    line.setAttribute('y2', pos[repo.name].y);
    line.setAttribute('stroke', '#FACC15');
    line.setAttribute('stroke-width', 1.5);
    line.setAttribute('stroke-opacity', 0.3);
    line.setAttribute('stroke-dasharray', '4,4');
    svg.appendChild(line);
  });

  // Nodo central (Vicente Vila)
  const cCircle = document.createElementNS(NS, 'circle');
  cCircle.setAttribute('cx', CX);
  cCircle.setAttribute('cy', CY);
  cCircle.setAttribute('r', 38);
  cCircle.setAttribute('fill', '#FACC15');
  cCircle.setAttribute('stroke', '#000');
  cCircle.setAttribute('stroke-width', 2);
  svg.appendChild(cCircle);

  const ct1 = document.createElementNS(NS, 'text');
  ct1.setAttribute('x', CX);
  ct1.setAttribute('y', CY - 6);
  ct1.setAttribute('text-anchor', 'middle');
  ct1.setAttribute('fill', '#000');
  ct1.setAttribute('font-weight', 'bold');
  ct1.setAttribute('font-size', '13');
  ct1.textContent = data.root ? data.root.name.split(' ')[0] : 'Vicente';
  svg.appendChild(ct1);

  const ct2 = document.createElementNS(NS, 'text');
  ct2.setAttribute('x', CX);
  ct2.setAttribute('y', CY + 12);
  ct2.setAttribute('text-anchor', 'middle');
  ct2.setAttribute('fill', '#000');
  ct2.setAttribute('font-weight', 'bold');
  ct2.setAttribute('font-size', '13');
  ct2.textContent = data.root ? data.root.name.split(' ').slice(1).join(' ') : 'Vila';
  svg.appendChild(ct2);

  // Nodos repos
  repos.forEach(repo => {
    const p = pos[repo.name];
    const mainTopic = (repo.topics && repo.topics[0]) ? repo.topics[0].code : '';
    const color = TOPIC_COLORS[mainTopic] || '#6B7280';

    const glow = document.createElementNS(NS, 'circle');
    glow.setAttribute('cx', p.x);
    glow.setAttribute('cy', p.y);
    glow.setAttribute('r', 30);
    glow.setAttribute('fill', color);
    glow.setAttribute('opacity', 0.15);
    svg.appendChild(glow);

    const circle = document.createElementNS(NS, 'circle');
    circle.setAttribute('cx', p.x);
    circle.setAttribute('cy', p.y);
    circle.setAttribute('r', 24);
    circle.setAttribute('fill', color);
    circle.setAttribute('stroke', '#1a1a2e');
    circle.setAttribute('stroke-width', 2);
    circle.style.cursor = 'pointer';
    circle.style.transition = 'r 0.2s';
    circle.addEventListener('mouseenter', () => {
      circle.setAttribute('r', 28);
      glow.setAttribute('r', 34);
    });
    circle.addEventListener('mouseleave', () => {
      circle.setAttribute('r', 24);
      glow.setAttribute('r', 30);
    });
    svg.appendChild(circle);

    const text = document.createElementNS(NS, 'text');
    text.setAttribute('x', p.x);
    text.setAttribute('y', p.y + 1);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('fill', '#fff');
    text.setAttribute('font-size', '10');
    text.setAttribute('font-weight', '600');
    text.textContent = repo.name.length > 10 ? repo.name.slice(0, 9) + '…' : repo.name;
    svg.appendChild(text);

    const title = document.createElementNS(NS, 'title');
    title.textContent = repo.name + '\nTopics: ' + (repo.topics || []).map(t => t.code).join(', ');
    circle.appendChild(title);
  });

  // Leyenda
  const usedTopics = Object.keys(TOPIC_COLORS).filter(t => topicMap[t]);
  const legendY = H - 20;
  const legendX = W - usedTopics.length * 85;
  usedTopics.forEach((topic, i) => {
    const x = legendX + i * 85;
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', x);
    c.setAttribute('cy', legendY);
    c.setAttribute('r', 5);
    c.setAttribute('fill', TOPIC_COLORS[topic]);
    svg.appendChild(c);

    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', x + 10);
    t.setAttribute('y', legendY + 4);
    t.setAttribute('fill', '#aaa');
    t.setAttribute('font-size', '10');
    t.textContent = topic;
    svg.appendChild(t);
  });
}
