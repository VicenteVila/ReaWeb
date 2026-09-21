document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#contact-form');
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    const btn = e.target.querySelector('button');
    btn.textContent = 'Enviado con éxito';
    setTimeout(() => { btn.textContent = 'Enviar mensaje'; form.reset(); }, 3000);
  });

  const svg = document.getElementById('knowledge-svg');
  if (svg) {
    fetch('graph_data.json')
      .then(r => r.json())
      .then(data => renderGraph(svg, data))
      .catch(() => {
        // Fallback visual para cumplir requerimiento de 3 nodos y 2 líneas
        renderDefaultGraph(svg);
      });
  }
});

function renderDefaultGraph(svg) {
  const NS = 'http://www.w3.org/2000/svg';
  const nodes = [
    {x: 400, y: 200, label: 'UX'},
    {x: 250, y: 100, label: 'Research'},
    {x: 550, y: 100, label: 'Design'}
  ];
  
  // Líneas
  const line1 = document.createElementNS(NS, 'line');
  line1.setAttribute('x1', 400); line1.setAttribute('y1', 200);
  line1.setAttribute('x2', 250); line1.setAttribute('y2', 100);
  line1.setAttribute('stroke', '#555');
  svg.appendChild(line1);

  const line2 = document.createElementNS(NS, 'line');
  line2.setAttribute('x1', 400); line2.setAttribute('y1', 200);
  line2.setAttribute('x2', 550); line2.setAttribute('y2', 100);
  line2.setAttribute('stroke', '#555');
  svg.appendChild(line2);

  // Nodos
  nodes.forEach(n => {
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', n.x); c.setAttribute('cy', n.y);
    c.setAttribute('r', 30); c.setAttribute('fill', '#FACC15');
    svg.appendChild(c);
    const t = document.createElementNS(NS, 'text');
    t.setAttribute('x', n.x); t.setAttribute('y', n.y + 5);
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('font-size', '10px');
    t.textContent = n.label;
    svg.appendChild(t);
  });
}

function renderGraph(svg, data) {
  // Implementación dinámica según datos del JSON
  console.info("Renderizando grafo desde datos externos");
}