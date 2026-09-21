document.addEventListener('DOMContentLoaded', () => {
    // Interacción simple: Hover de entrada
    const cta = document.querySelector('.cta-button');
    cta.addEventListener('mouseenter', () => {
        cta.style.transform = 'rotate(0deg) scale(1.05)';
    });
    cta.addEventListener('mouseleave', () => {
        cta.style.transform = 'rotate(-3deg) scale(1)';
    });

    // Fetch del grafo de conocimientos (placeholder según requisitos)
    const renderGraph = (data) => {
        console.log("Grafo renderizado con:", data);
        // Implementación de SVG dinámico iría aquí
    };

    fetch('graph_data.json')
        .then(r => r.json())
        .then(d => renderGraph(d))
        .catch(() => {
            // Silencioso si no hay json
        });

    // Formulario simple
    document.getElementById('contact-form').addEventListener('submit', (e) => {
        e.preventDefault();
        alert('Gracias, te responderé en 24h.');
    });
});