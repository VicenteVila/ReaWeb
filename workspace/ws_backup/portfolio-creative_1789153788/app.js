document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#contact-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      alert('Gracias por tu mensaje, responderé en 24h.');
    });
  }

  const svg = document.getElementById('knowledge-svg');
  if (svg) {
    fetch('graph_data.json')
      .then(r => r.json())
      .then(d => renderGraph(svg, d))
      .catch(() => {
        const NS = 'http://www.w3.org/2000/svg';
        const cCircle = document.createElementNS(NS, 'circle');
        cCircle.setAttribute('cx', 400);
        cCircle.setAttribute('cy', 200);
        cCircle.setAttribute('r', 40);
        cCircle.setAttribute('fill', '#FACC15');
        svg.appendChild(cCircle);
      });
  }
});

function renderGraph(svg, data) {
  const NS = 'http://www.w3.org/2000/svg';
  svg.innerHTML = '';
  const root = document.createElementNS(NS, 'text');
  root.setAttribute('x', '50%');
  root.setAttribute('y', '50%');
  root.setAttribute('text-anchor', 'middle');
  root.setAttribute('fill', '#FAFAF9');
  root.setAttribute('font-size', '20px');
  root.textContent = 'Vicente Vila';
  svg.appendChild(root);
}