document.addEventListener('DOMContentLoaded', () => {
  const svg = document.getElementById('knowledge-svg');
  if (svg) {
    fetch('graph_data.json')
      .then(r => r.json())
      .then(data => renderGraph(svg, data))
      .catch(() => {
        // Fallback visual para el grafo si no hay archivo
        renderGraph(svg, { repos: [
          { name: 'UX', topic: 'cs.AI' },
          { name: 'UI', topic: 'cs.SE' },
          { name: 'Research', topic: 'cs.CL' }
        ]});
      });
  }
});

function renderGraph(svg, data) {
  const repos = data.repos || [];
  const W = 800, H = 400, CX = W/2, CY = H/2, R = 100;
  const NS = 'http://www.w3.org/2000/svg';
  
  // Nodo central
  const center = document.createElementNS(NS, 'circle');
  center.setAttribute('cx', CX);
  center.setAttribute('cy', CY);
  center.setAttribute('r', 30);
  center.setAttribute('fill', '#DB2777');
  svg.appendChild(center);

  repos.forEach((repo, i) => {
    const angle = (2 * Math.PI * i) / repos.length - Math.PI / 2;
    const x = CX + R * Math.cos(angle);
    const y = CY + R * Math.sin(angle);
    
    // Linea
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('x1', CX); line.setAttribute('y1', CY);
    line.setAttribute('x2', x); line.setAttribute('y2', y);
    line.setAttribute('stroke', '#444');
    svg.appendChild(line);

    // Nodo
    const circle = document.createElementNS(NS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    circle.setAttribute('r', 20);
    circle.setAttribute('fill', repo.topic === 'cs.AI' ? '#3b82f6' : repo.topic === 'cs.SE' ? '#22c55e' : '#a855f7');
    svg.appendChild(circle);
  });
}