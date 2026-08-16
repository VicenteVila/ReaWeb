# REGLAS ESPECÍFICAS - LANDING PAGE
# Extensión de global-rules.md

## 1. ESTRUCTURA ESPECÍFICA

LANDING_PAGE_SECTIONS:
  - Hero: Value proposition principal, CTA claro
  - Social Proof: Logos de clientes, testimonials, reviews
  - Features: 3-6 características principales (grid o cards)
  - How it Works: Proceso paso a paso (3-4 pasos máximo)
  - Pricing: Si aplica, simple y transparente
  - FAQ: Acordeón con preguntas frecuentes
  - Final CTA: Repetir call-to-action
  - Footer: Links legales, redes sociales, newsletter

## 2. DISEÑO

LANDING_DESIGN_RULES:
- Above the fold: Mensaje principal + CTA visible sin scroll
- Jerarquía visual clara: H1 &gt; H2 &gt; H3 con pesos de fuente distintos
- Espacio en blanco generoso (no saturar)
- CTAs contrastantes (color primario fuerte)
- Uso estratégico de imágenes humanas (conexión emocional)
- Animaciones sutiles (fade in, slide up) no distraer
- Trust signals visibles (seguridad, garantías)

## 3. CONVERSIÓN OPTIMIZACIÓN

CONVERSION_RULES:
- Un objetivo principal por página (una acción prioritaria)
- Formularios cortos (máximo 3-4 campos iniciales)
- Microcopy útil en labels y placeholders
- Urgencia/escasez solo si es real (no fake countdowns)
- Testimonials con foto, nombre, cargo y empresa reales
- Garantías visibles (money-back, secure payment)

## 4. TECNOLOGÍA RECOMENDADA

TECH_STACK_LANDING:
- Framework: Next.js (App Router) o Astro (mejor performance)
- Styling: Tailwind CSS + Framer Motion (animaciones)
- Forms: React Hook Form + Zod (validación)
- Analytics: Google Analytics 4 + Meta Pixel
- Heatmaps: Hotjar o Microsoft Clarity

## 5. PERFORMANCE CRÍTICA

LANDING_PERFORMANCE:
- First Contentful Paint &lt; 1.8s
- Time to Interactive &lt; 3.8s
- Optimización extrema de imágenes (WebP, lazy, blur-up)
- Preload de fuentes críticas
- Inline critical CSS