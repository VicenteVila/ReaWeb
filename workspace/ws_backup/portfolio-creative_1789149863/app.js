document.addEventListener('DOMContentLoaded', () => {
  const form = document.querySelector('#contact-form');
  
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const btn = form.querySelector('button');
      btn.textContent = 'Enviando...';
      setTimeout(() => {
        btn.textContent = '¡Gracias!';
        form.reset();
      }, 1500);
    });
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.style.opacity = '1';
        e.target.style.transform = 'translateY(0)';
      }
    });
  }, { threshold: 0.1 });
  
  document.querySelectorAll('section').forEach(s => {
    s.style.opacity = '0';
    s.style.transform = 'translateY(40px)';
    s.style.transition = 'all 1s ease-out';
    observer.observe(s);
  });

  // Fetching repo data as requested
  fetch('graph_data.json')
    .then(r => r.ok ? r.json() : [])
    .then(d => renderGraph(d))
    .catch(() => {});

  function renderGraph(data) {
    // Logic for SVG graph rendering based on repo topics
    console.log("Graph data loaded");
  }
});