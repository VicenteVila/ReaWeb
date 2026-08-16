# WORKFLOWS ESPECÍFICOS - LANDING PAGE

## WORKFLOW: /landing-optimize-conversion
DESCRIPCIÓN: Optimizar elementos de conversión
CUÁNDO_USAR: Cuando conversion rate es bajo o al lanzar

PASOS:
1. Analizar funnel de conversión actual
2. A/B test de headlines principales (3 variantes)
3. Optimizar posición y color de CTAs
4. Reducir campos de formularios al mínimo necesario
5. Agregar urgency elements si aplica (contadores reales)
6. Mejorar social proof (más testimonials, logos reconocidos)
7. Implementar sticky header con CTA en mobile
8. Verificar velocidad de carga en 3G
9. Testear en múltiples dispositivos reales

## WORKFLOW: /landing-section-create
DESCRIPCIÓN: Crear nueva sección de landing page
CUÁNDO_USAR: Al agregar secciones nuevas

PASOS:
1. Identificar tipo de sección según LANDING_PAGE_SECTIONS
2. Determinar posición en el flujo de la página
3. Diseñar layout responsive (mobile-first)
4. Implementar animaciones de entrada (scroll-triggered)
5. Optimizar imágenes para carga progresiva
6. Asegurar CTA claro si aplica
7. Verificar contraste y legibilidad
8. Testear en todos los breakpoints

## WORKFLOW: /landing-analytics-setup
DESCRIPCIÓN: Configurar tracking completo de conversión
CUÁNDO_USAR: Al inicio del proyecto

PASOS:
1. Configurar Google Analytics 4 con eventos custom:
   - scroll_depth (25%, 50%, 75%, 90%)
   - cta_clicks (por botón)
   - form_starts y form_completions
   - video_plays (si hay video)
2. Configurar Google Tag Manager
3. Setup Meta Pixel si aplica tráfico paid
4. Configurar conversion goals
5. Crear dashboard de analytics
6. Setup Hotjar recordings y heatmaps