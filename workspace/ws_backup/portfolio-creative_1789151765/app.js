document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#contact-form');
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    alert('Gracias por tu mensaje. Responderé en 24h.');
  });

  const svg = document.getElementById('knowledge-svg');
  if (svg) {
    fetch('graph_data.json')
      .then(r => r.json())
      .then(data => renderGraph(svg, data))
      .catch(() => {
        renderGraph(svg, { nodes: [{ id: 'UX', topic: 'cs.SE' }] });
      });
  }
});

function renderGraph(svg, data) {
  const NS = 'http://www.w3.org/2000/svg';
  const W = 800, H = 400, CX = W/2, CY = H/2;
  
  // Nodos de ejemplo basados en el sistema de diseño
  const cCircle = document.createElementNS(NS, 'circle');
  cCircle.setAttribute('cx', CX); 
  cCircle.setAttribute('cy', CY);
  cCircle.setAttribute('r', 50); 
  cCircle.setAttribute('fill', '#FACC15');
  svg.appendChild(cCircle);
  
  const text = document.createElementNS(NS, 'text');
  text.setAttribute('x', CX); 
  text.setAttribute('y', CY + 5);
  text.setAttribute('text-anchor', 'middle');
  text.setAttribute('fill', '#000');
  text.setAttribute('font-weight', 'bold');
  text.setAttribute('font-size', '14px');
  text.textContent = 'UX DESIGNER';
  svg.appendChild(text);
}