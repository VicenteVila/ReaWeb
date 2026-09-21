document.addEventListener('DOMContentLoaded', () => {
    // Renderizado de grafo dinámico basado en JSON
    fetch('graph_data.json')
        .then(r => r.json())
        .then(d => renderGraph(d))
        .catch(() => console.info("Grafo: No se encontró graph_data.json"));

    function renderGraph(data) {
        const container = document.getElementById('graph-container');
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 800 500");
        container.appendChild(svg);
        
        // Lógica de nodos y edges dinámica aquí...
    }

    // Interacción formulario
    const form = document.querySelector('#contact-form');
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        alert('Gracias por tu mensaje. Responderé en 24h.');
    });
});