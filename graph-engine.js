/**
 * Vicente Vila - Knowledge Graph (SVG puro, Vanilla JS) + Flujogramas Mermaid
 *
 * Mejoras vs referencia:
 *  - 8 repositorios (AgentFlow, ReaWeb, ReaGame, TraceForge, CogniTeam,
 *    PromptForge, Asubarnipal, PopeBot-agente).
 *  - Tercer nodo hijo "Flujogramas" que renderiza los diagramas Mermaid (.mmd)
 *    del repo con mermaid.min.js bundled local.
 *  - Las aristas padre->hijo salen del BORDE SUPERIOR del círculo del nodo repo.
 *  - Repos sin .mmd (PromptForge, PopeBot-agente) muestran aviso, sin inventar.
 *  - mermaid.js local (mermaid.min.js), sin CDN.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

// Datos del grafo ahora leídos dinámicamente de repos.json
let graphData = {
    "root": { "name": "Vicente Vila", "email": "vicentevilaramirez@gmail.com" },
    "repos": []
};

// Cargar repositorios dinámicamente

// Manifesto de flujogramas por repo (archivos .mmd disponibles). PromptForge y
// PopeBot-agente NO tienen flujogramas -> se muestra aviso.
const FLUJOGRAMAS_MANIFEST = {
    "AgentFlow": ["agentflow_L0_Overview.mmd", "agentflow_L1_Agentflow.mmd"],
    "Asubarnipal": ["asubarnipal_L0_Overview.mmd", "asubarnipal_L1_Api.mmd", "asubarnipal_L1_App_Service.mmd", "asubarnipal_L1_Config.mmd", "asubarnipal_L1_Core.mmd", "asubarnipal_L1_Dashboard.mmd", "asubarnipal_L1_Examples.mmd", "asubarnipal_L1_Index_Rag.mmd", "asubarnipal_L1_Interface.mmd", "asubarnipal_L1_Scripts.mmd", "asubarnipal_L1_Skills.mmd"],
    "CogniTeam": ["cogniteam_L0_Overview.mmd", "cogniteam_L1_Cogniteam.mmd", "cogniteam_L1_Experiments_Crear_proyecto_godot.mmd", "cogniteam_L1_Main.mmd", "cogniteam_L1_Scripts.mmd"],
    "ReaGame": ["reagame_L0_Overview.mmd", "reagame_L1_Agent.mmd", "reagame_L1_Config.mmd", "reagame_L1_Scripts.mmd", "reagame_L1_Tools.mmd"],
    "ReaWeb": ["reaweb_L0_Overview.mmd", "reaweb_L1_Agent.mmd", "reaweb_L1_Config.mmd", "reaweb_L1_Scripts.mmd", "reaweb_L1_Tools.mmd", "reaweb_L1_phased_horizontal.mmd", "reaweb_L1_radial.mmd"],
    "TraceForge": ["traceforge_L0_Overview.mmd", "traceforge_L1_Examples.mmd", "traceforge_L1_Traceforge.mmd"],
    "PromptForge": [],
    "PopeBot-agente": []
};

// Taxonomía de arXiv (Computer Science): explicación ampliada de cada categoría
// que puede aparecer en los "Conocimientos IA" de los repositorios.
const TAXONOMY = {
    "cs.AI": "Inteligencia Artificial: razonamiento, planificación, representación del conocimiento, búsqueda y agentes autónomos. Cubre la construcción de sistemas que perciben, razonan y actúan de forma autónoma.",
    "cs.SE": "Ingeniería del Software: ciclo de vida del desarrollo de software, arquitectura, herramientas de análisis estático y visualización, testing, integración continua y automatización del código.",
    "cs.CL": "Computación y Lenguaje (Procesamiento de Lenguaje Natural): modelos de lenguaje, traducción, generación de texto, comprensión semántica y técnicas basadas en LLMs.",
    "cs.MA": "Sistemas Multi-Agente: coordinación, negociación y orquestación de múltiples agentes autónomos que colaboran para alcanzar objetivos conjuntos.",
    "cs.LG": "Aprendizaje Automático (Machine Learning): algoritmos de aprendizaje, optimización de políticas, entrenamiento de modelos con feedback y selección adaptativa de datos.",
    "cs.IR": "Recuperación de Información: búsqueda, indexación vectorial, re-ranking y sistemas de recuperación híbrida sobre bases de conocimiento y documentos.",
    "cs.CV": "Visión por Computador: análisis e interpretación de imágenes, detección de objetos, OCR y modelos de visión artificial.",
    "cs.DC": "Computación Distribuida: infraestructura distribuida y en la nube, ejecución paralela de tareas y sistemas de cómputo a gran escala."
};

const CENTER = { x: 400, y: 320 };
const REPO_RADIUS = 148;           // distancia repos -> centro
const CHILD_OFFSET = 88;           // distancia hijo -> borde exterior del repo
const ROOT_R = 42;
const REPO_R = 32;
const CHILD_R = 30;
const STEM_LEN = 50;               // longitud del tallo de la "T" (origen -> hub)

// Colores base para los gradientes radiales de los nodos (orbe neon).
const NODE_GRADIENTS = {
    'root-node':   ['#a5d8ff', '#3b82f6', '#1d3f9e'],
    'repo-node':   ['#9ad0ff', '#38bdf8', '#1e4fa8'],
    'topics-node': ['#a7f3d0', '#34d399', '#0f766e'],
    'readme-node': ['#fde68a', '#fbbf24', '#b45309'],
    'flow-node':   ['#e9d5ff', '#a78bfa', '#6d28d9']
};

let graphData = GRAPH_DATA_FALLBACK;

// Esquemas visuales (infogramas .jfif) por repositorio. PopeBot-agente no
// tiene esquema -> queda fuera del mapa y no se muestra nada en su hover.
const INFOGRAMAS = {
    "AgentFlow": "Infogramas/AgentFlow.jfif",
    "ReaWeb": "Infogramas/ReaWeb%20Harness.jfif",
    "ReaGame": "Infogramas/ReaGame%20Harness.jfif",
    "TraceForge": "Infogramas/TraceForge.jfif",
    "CogniTeam": "Infogramas/CogniTeam%20Harness.jfif",
    "PromptForge": "Infogramas/PromptForge.jfif",
    "Asubarnipal": "Infogramas/Asubarnipal%20Harness.jfif"
};

// Resumen "qué es y qué hace" por repositorio (frases reales de cada README).
const REPO_SUMMARY = {
    "AgentFlow": "Parse and visualize AI agent control flows as Excalidraw diagrams and SVG. Lee el código Python de un agente, extrae el control flow vía análisis AST (bucles, decisiones, despacho de herramientas, hooks de auto-evolución) y lo renderiza como Excalidraw editable o SVG standalone, sin dependencias externas.",
    "ReaWeb": "Agente ReASearch de optimización web: dado un arquetipo y una tarea, desarrolla páginas iterativamente (genera candidato, audita, mejora) y, además, evoluciona su propio harness (reglas, skills y workflows en domain/).",
    "ReaGame": "Agente ReASearch especializado en desarrollo de juegos Godot 4. Fork limpio del core genérico de reaweb-harness (mismo loop de exploración/explotación, métricas, lecciones, caché y gobernanza de skills) con una capa específica de juegos.",
    "TraceForge": "Structured tracing for multi-agent LLM pipelines: trazado estructurado de los flujos multi-agente para entender y depurar cada paso de sus pipelines de LLMs.",
    "CogniTeam": "Sistema multi-agente en Python que recibe una tarea en lenguaje natural, la clasifica en un dominio y arquetipo (14 dominios, 61 arquetipos), genera un plan de pasos con las herramientas disponibles, lo ejecuta, valida los resultados y deja un reporte de la ejecución con todas las llamadas LLM registradas.",
    "PromptForge": "CI/CD para prompts de LLMs: versiona prompts en YAML, testea regresiones contra datasets de evaluación y los optimiza automáticamente (inspirado en DSPy, pero free-tier).",
    "Asubarnipal": "Agente autónomo con interfaz de Telegram, knowledge base RAG, memoria híbrida (H-Mem) y dashboard de analítica en tiempo real.",
    "PopeBot-agente": "The repository IS the agent: cada acción que tu agente hace es un git commit. Ves exactamente qué hizo, cuándo y por qué; si lo fastidia, revierte."
};

// Resumen personal del nodo raíz: aterrizar conocimientos nuevos de IA en
// agentes y flujos de trabajo; estar al día en construcción, evaluación y
// trazado de agentes. Sin edulcorantes.
const ROOT_SUMMARY = {
    title: "Vicente Vila",
    text: "Aterrizo conocimientos nuevos de IA en agentes y flujos de trabajo: mi objetivo es estar a la última en construcción, evaluación y trazado de agentes de IA. Hoy esto es un portafolio en montaje — ocho repos de agentes con README, analizadores e infogramas y un harness genérico que intento que se sostenga solo. Sin fanfarria: el valor está por demostrarse en uso real; el trabajo visible es el que ves aquí."
};

// Tipo de repositorio: 'arnes' (agentes que llevan un LLM) o 'herramienta'.
// Define la etiqueta del botón "Ver Arnés" / "Ver Herramienta" del panel fijo.
const REPO_KIND = {
    "ReaWeb": "arnes",
    "ReaGame": "arnes",
    "CogniTeam": "arnes",
    "Asubarnipal": "arnes",
    "PopeBot-agente": "arnes",
    "AgentFlow": "herramienta",
    "TraceForge": "herramienta",
    "PromptForge": "herramienta"
};

// Inyecta gradientes radiales ("orbes") en <defs> del SVG principal.
function ensureGradients() {
    const svg = document.getElementById('main-svg');
    let defs = svg.querySelector('defs');
    if (!defs) {
        defs = document.createElementNS(SVG_NS, 'defs');
        svg.insertBefore(defs, svg.firstChild);
    }
    Object.keys(NODE_GRADIENTS).forEach((cls) => {
        const [c0, c1, c2] = NODE_GRADIENTS[cls];
        const id = `grad-${cls}`;
        if (defs.querySelector(`#${id}`)) return;
        const g = document.createElementNS(SVG_NS, 'radialGradient');
        g.setAttribute('id', id);
        g.setAttribute('cx', '35%');
        g.setAttribute('cy', '30%');
        g.setAttribute('r', '80%');
        [[0, c0], [0.55, c1], [1, c2]].forEach(([off, col]) => {
            const st = document.createElementNS(SVG_NS, 'stop');
            st.setAttribute('offset', String(off));
            st.setAttribute('stop-color', col);
            g.appendChild(st);
        });
        defs.appendChild(g);
    });
}

function initGraph() {
    const nodesLayer = document.getElementById('nodes-layer');
    const edgesLayer = document.getElementById('edges-layer');
    ensureGradients();

    // 1. Nodo Raíz (Vicente Vila + email) en el centro
    const root = createNode(nodesLayer, CENTER.x, CENTER.y, graphData.root.name, 'root-node', ROOT_R, () => {
        window.location.href = `mailto:${graphData.root.email}`;
    }, `Vicente Vila - ${graphData.root.email} - Click para enviar email`);
    root.appendChild(makeTspanEmail(CENTER.x, CENTER.y));

    // Resumen personal al hacer hover sobre el nodo raíz.
    root.addEventListener('mouseenter', () => showRootInfo());
    root.addEventListener('focusin', () => showRootInfo());
    root.addEventListener('mouseleave', hideInfo);
    root.addEventListener('focusout', hideInfo);

    // 2. Nodos de Repositorios alrededor del raíz (sin PopeBot-agente)
    graphData.repos.filter(r => r.name !== 'PopeBot-agente')
        .forEach((repo, index) => {
        const angle = (index / graphData.repos.length) * 2 * Math.PI - Math.PI / 2;
        const rx = CENTER.x + REPO_RADIUS * Math.cos(angle);
        const ry = CENTER.y + REPO_RADIUS * Math.sin(angle);

        // Grupo contenedor repo + hijos (hover conjunto)
        const repoGroup = document.createElementNS(SVG_NS, 'g');
        repoGroup.setAttribute('class', 'repo-group');
        repoGroup.setAttribute('tabindex', '0');
        nodesLayer.appendChild(repoGroup);

        // Arista Raíz (borde) -> Repo
        const rootEdgeX = CENTER.x + Math.cos(angle) * ROOT_R;
        const rootEdgeY = CENTER.y + Math.sin(angle) * ROOT_R;
        createEdge(edgesLayer, rootEdgeX, rootEdgeY, rx, ry, 'edge-main');

        // Grupo de hijos desplegables
        const childGroup = document.createElementNS(SVG_NS, 'g');
        childGroup.setAttribute('class', 'child-group');
        repoGroup.appendChild(childGroup);

        // Nodo repo (el "padre" azul que esconde/muestra los hijos al hover).
        // Se añade ANTES de los hijos para que quede debajo y el hover del grupo
        // despliegue los nodos hijos al pasar por encima del repo.
        const repoNode = createNode(repoGroup, rx, ry, repo.name, 'repo-node', REPO_R, null,
            `Repo: ${repo.name} - Click para fijar ver el resumen e infograma`);
        repoNode.addEventListener('click', (e) => { e.stopPropagation(); togglePin(repo.name, repoNode); });
        repoNode.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); togglePin(repo.name, repoNode); }
        });
        repoGroup.appendChild(childGroup);

        // 3 nodos hijos, saliendo del BORDE SUPERIOR del círculo del repo
        const childTypes = [
            { label: 'Conocimientos\nIA', cls: 'topics-node', onClick: () => showTopics(repo.name, repo.topics), aria: `Conocimientos IA de ${repo.name}` },
            { label: 'README', cls: 'readme-node', onClick: () => { window.location.href = `repos/${repo.name}/index.html`; }, aria: `Ver README de ${repo.name}` },
            { label: 'Flujogramas', cls: 'flow-node', onClick: () => openFlujogramas(repo.name), aria: `Flujogramas de ${repo.name}` }
        ];

        // Origen en el BORDE EXTERIOR del círculo del repo (dirección radial).
        const originX = rx + REPO_R * Math.cos(angle);
        const originY = ry + REPO_R * Math.sin(angle);

        // Hub central de la "T": en la dirección radial, a la mitad del abanico.
        const hubX = originX + STEM_LEN * Math.cos(angle);
        const hubY = originY + STEM_LEN * Math.sin(angle);

        // Tallo de la "T": del borde del repo al hub (flecha de flujo animada).
        createEdge(childGroup, originX, originY, hubX, hubY, 'edge stem-child flow-edge');

        // 3 hijos abanicados alrededor de la dirección radial hacia afuera
        // (sentido horario). Cada rama de la "T" va del hub al hijo.
        childTypes.forEach((c, i) => {
            const spread = (i - 1) * 0.45;              // -0.45, 0, +0.45 rad
            const childAngle = angle + spread;          // rotación radial (horaria)
            const cx = originX + CHILD_OFFSET * Math.cos(childAngle);
            const cy = originY + CHILD_OFFSET * Math.sin(childAngle);

            // Rama de la "T": del hub al hijo (flecha de flujo animada).
            createEdge(childGroup, hubX, hubY, cx, cy, 'edge branch-child flow-edge');

            // Nodo hijo con texto dentro (radio >= 30)
            createNode(childGroup, cx, cy, c.label, c.cls, CHILD_R, c.onClick, c.aria);
        });

        // Infograma del repo al hover (tarjeta flotante glass)
        // Resumen (izquierda) + infograma (derecha) al hacer hover del repo
        setupRepoHover(repoGroup, repo.name);
    });
}

// --- Infogramas (esquemas visuales por repositorio) ---

// --- Paneles laterales (resumen izq. + infograma der.) ---

function hideInfo() {
    const sum = document.getElementById('summary-panel');
    const img = document.getElementById('infograma-panel');
    if (sum) sum.classList.remove('visible');
    if (img) img.classList.remove('visible');
}

// Rellena y muestra el resumen (izquierda) y el infograma (derecha) de un repo.
function showRepoInfo(repoName) {
    const sum = document.getElementById('summary-panel');
    if (sum) {
        document.getElementById('summary-title').textContent = repoName;
        document.getElementById('summary-text').textContent =
            REPO_SUMMARY[repoName] || 'Sin descripción disponible.';
        document.getElementById('summary-tag').textContent = 'Repositorio';
        sum.classList.add('visible');
    }
    const right = document.getElementById('infograma-panel');
    const src = INFOGRAMAS[repoName];
    if (right) {
        right.classList.remove('visible');
        if (src) {
            const imgp = right.querySelector('img');
            imgp.src = src;
            imgp.onload = () => imgp.classList.add('loaded');
            right.querySelector('.caption').textContent = repoName;
            right.classList.add('visible');
        }
    }
}

// Muestra solo el resumen personal en el nodo raíz (sin imagen derecha).
function showRootInfo() {
    document.getElementById('summary-title').textContent = ROOT_SUMMARY.title;
    document.getElementById('summary-text').textContent = ROOT_SUMMARY.text;
    document.getElementById('summary-tag').textContent = 'Nodo principal';
    document.getElementById('summary-panel').classList.add('visible');
    document.getElementById('infograma-panel').classList.remove('visible');
}

function setupRepoHover(group, repoName) {
    group.addEventListener('mouseenter', () => showRepoInfo(repoName));
    group.addEventListener('focusin', () => showRepoInfo(repoName));
    group.addEventListener('mouseleave', hideInfo);
    group.addEventListener('focusout', hideInfo);
}

// --- Panel fijo abajo-derecha (pin al hacer click en un repo) + lightbox ---

let pinnedRepo = null;
let pinnedNodeEl = null;

function unpin() {
    pinnedRepo = null;
    if (pinnedNodeEl) { pinnedNodeEl.classList.remove('pinned'); pinnedNodeEl = null; }
    const dock = document.getElementById('pin-dock');
    if (dock) dock.classList.remove('visible');
}

// Ancla el resumen del repo en el panel inferior derecho, con el botón
// "Ver Arnés" (agentes con LLM) / "Ver Herramienta" (resto) -> lightbox.
function renderPin(name, nodeEl) {
    const dock = document.getElementById('pin-dock');
    if (!dock) return;

    if (pinnedNodeEl) pinnedNodeEl.classList.remove('pinned');
    pinnedNodeEl = nodeEl || null;
    if (pinnedNodeEl) pinnedNodeEl.classList.add('pinned');

    document.getElementById('pin-title').textContent = name;
    document.getElementById('pin-text').textContent =
        REPO_SUMMARY[name] || 'Sin descripción disponible.';
    document.getElementById('pin-tag').textContent = 'Repositorio';

    const ver = document.getElementById('ver-btn');
    const hasImg = !!INFOGRAMAS[name];
    if (ver) {
        if (hasImg) {
            ver.style.display = '';
            ver.textContent = REPO_KIND[name] === 'arnes' ? 'Ver Arnés' : 'Ver Herramienta';
            ver.onclick = () => openFullImage(name);
        } else {
            ver.style.display = 'none';   // sin infograma -> sin botón ver imagen
        }
    }
    dock.classList.add('visible');
}

function togglePin(name, nodeEl) {
    if (pinnedRepo === name) unpin();
    else { pinnedRepo = name; renderPin(name, nodeEl); }
}

function openFullImage(name) {
    const src = INFOGRAMAS[name];
    if (!src) return;
    const img = document.getElementById('fullimg-img');
    img.src = src;
    img.onload = () => img.classList.add('loaded');
    document.getElementById('fullimg-overlay').classList.add('visible');
    document.body.classList.add('locked');
}

function closeFullImage() {
    document.getElementById('fullimg-overlay').classList.remove('visible');
    document.body.classList.remove('locked');
}

function createNode(parent, x, y, label, className, radius, onClick, ariaLabel) {
    const g = document.createElementNS(SVG_NS, 'g');
    g.setAttribute('class', `node ${className}`);
    g.setAttribute('role', 'button');
    g.setAttribute('aria-label', ariaLabel);
    g.setAttribute('tabindex', '0');

    const ring = document.createElementNS(SVG_NS, 'circle');
    ring.setAttribute('class', 'halo');
    ring.setAttribute('cx', x);
    ring.setAttribute('cy', y);
    ring.setAttribute('r', radius + 4);
    // color del anillo según la clase del nodo
    const gradKey = Object.keys(NODE_GRADIENTS).find(k => className.includes(k));
    const ringColor = gradKey ? NODE_GRADIENTS[gradKey][1] : 'currentColor';
    ring.setAttribute('stroke', ringColor);

    const circle = document.createElementNS(SVG_NS, 'circle');
    circle.setAttribute('cx', x);
    circle.setAttribute('cy', y);
    circle.setAttribute('r', radius);
    circle.setAttribute('fill', `url(#grad-${gradKey || 'repo-node'})`);
    circle.setAttribute('stroke', ringColor);
    circle.setAttribute('stroke-opacity', '0.55');

    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', x);
    text.setAttribute('y', y);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');

    const lines = String(label).split('\n');
    lines.forEach((line, i) => {
        const tspan = document.createElementNS(SVG_NS, 'tspan');
        tspan.setAttribute('x', x);
        tspan.setAttribute('dy', i === 0
            ? (lines.length > 1 ? -(lines.length - 1) * 0.55 : 0) + 'em'
            : '1.1em');
        tspan.textContent = line;
        text.appendChild(tspan);
    });

    g.appendChild(ring);
    g.appendChild(circle);
    g.appendChild(text);

    if (className.includes('repo-node')) {
        const pulse = document.createElementNS(SVG_NS, 'circle');
        pulse.setAttribute('class', 'pulse');
        pulse.setAttribute('cx', x);
        pulse.setAttribute('cy', y);
        pulse.setAttribute('r', 32);
        g.appendChild(pulse);
    }

    if (onClick) {
        g.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
        g.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }
        });
    }

    parent.appendChild(g);
    return g;
}

// Para el nodo raíz: muestra el email debajo del nombre (multilínea real)
function makeTspanEmail(x, y) {
    const t = document.createElementNS(SVG_NS, 'text');
    t.setAttribute('x', x);
    t.setAttribute('y', y + 16);
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('dominant-baseline', 'middle');
    t.setAttribute('class', 'root-email');
    t.textContent = graphData.root.email;
    return t;
}

function createEdge(parent, x1, y1, x2, y2, className) {
    const line = document.createElementNS(SVG_NS, 'line');
    line.setAttribute('x1', x1);
    line.setAttribute('y1', y1);
    line.setAttribute('x2', x2);
    line.setAttribute('y2', y2);
    line.setAttribute('class', `edge ${className}`);
    parent.appendChild(line);
}

function showTopics(repoName, topics) {
    const panel = document.getElementById('details-panel');
    document.getElementById('panel-title').textContent = `Conocimientos IA: ${repoName}`;
    document.getElementById('topics-list').innerHTML = topics.map(t => {
        const taxo = TAXONOMY[t.code];
        const taxoHtml = taxo
            ? `<div class="taxo-desc">${taxo}</div>`
            : '';
        return `
        <div class="topics-item">
            <code>${t.code}</code>
            ${taxoHtml}
            <p class="topic-desc">${t.desc}</p>
        </div>
    `;
    }).join('');
    panel.classList.remove('hidden');
    document.body.classList.add('has-panel');
}

// --- Flujogramas ---
// Cada diagrama .mmd tiene su propia página HTML autocontenida
// (flujogramas/<repo>/<nombre>.html). Desde la landing se abre en pestaña
// nueva, sin depender de fetch/render en runtime (funciona por file:// y HTTP).
function openFlujogramas(repoName) {
    const panel = document.getElementById('mermaid-panel');
    const selector = document.getElementById('mermaid-selector');
    const content = document.getElementById('mermaid-content');
    document.getElementById('mermaid-title').textContent = `Flujogramas: ${repoName}`;

    const files = FLUJOGRAMAS_MANIFEST[repoName] || [];
    if (!files.length) {
        selector.innerHTML = '';
        content.innerHTML = '<p class="mermaid-empty">Sin flujogramas disponibles para este repositorio.</p>';
        panel.classList.remove('hidden');
        document.body.classList.add('has-panel');
        return;
    }

    selector.innerHTML = files.map(f => {
        const base = f.replace(/\.mmd$/i, '');
        const href = `flujogramas/${repoName}/${base}.html`;
        return `<a class="mmd-btn" href="${href}" target="_blank" rel="noopener">${base}</a>`;
    }).join('');

    content.innerHTML = '<p class="mermaid-empty">Cada flujograma se abre en una pestaña nueva.</p>';
    panel.classList.remove('hidden');
    document.body.classList.add('has-panel');
}

// --- Theme Logic ---
const themeToggle = document.getElementById('theme-toggle');
const body = document.body;
function toggleTheme() {
    const isDark = body.classList.toggle('dark-theme');
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
}

function closePanel(id) {
    document.getElementById(id).classList.add('hidden');
    const anyOpen = !document.getElementById('details-panel').classList.contains('hidden')
        || !document.getElementById('mermaid-panel').classList.contains('hidden');
    if (!anyOpen) document.body.classList.remove('has-panel');
}

// Cierra paneles si el usuario hace click fuera (en el overlay).
function setupPanelOverlay() {
    const overlay = document.querySelector('.panel-overlay');
    if (overlay) {
        overlay.addEventListener('click', () => {
            closePanel('details-panel');
            closePanel('mermaid-panel');
        });
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Cargar tema guardado
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme === 'light') body.classList.remove('dark-theme');
    else if (savedTheme === 'dark') body.classList.add('dark-theme');
    else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
        body.classList.remove('dark-theme');
    }

    // Dibujar el grafo inmediatamente con los datos (ahora dinámicos)
    // initGraph() se llama dentro del .then del fetch de repos.json
    
    // fetch('graph_data.json') -> eliminado, ya usamos repos.json

    themeToggle.addEventListener('click', toggleTheme);
    const fullOverlay = document.getElementById('fullimg-overlay');
    const fullClose = document.getElementById('fullimg-close');
    if (fullOverlay) fullOverlay.addEventListener('click', (e) => {
        if (e.target === fullOverlay || e.target === fullClose) closeFullImage();
    });
    if (fullClose) fullClose.addEventListener('click', closeFullImage);

    window.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closePanel('details-panel');
            closePanel('mermaid-panel');
            if (fullOverlay && fullOverlay.classList.contains('visible')) closeFullImage();
        }
    });
});
