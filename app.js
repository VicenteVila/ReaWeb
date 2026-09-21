document.addEventListener('DOMContentLoaded', () => {
  const grid = document.querySelector('#projects-grid');
  
  fetch('repos.json')
    .then(r => r.json())
    .then(data => {
      // Renderizar grid de proyectos
      data.repos.forEach(repo => {
        const article = document.createElement('article');
        article.className = 'card';
        article.innerHTML = `
          <h3>${repo.name}</h3>
          <p>${repo.description}</p>
          <div class="tags">${repo.topics.map(t => `<span>${t}</span>`).join('')}</div>
        `;
        grid.appendChild(article);
      });
    });
});
