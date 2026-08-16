# WORKFLOWS GLOBALES - UNIVERSALES
# Activación: Disponibles en todos los proyectos con '/nombre-workflow'

## WORKFLOW: /project-setup
DESCRIPCIÓN: Inicialización de cualquier proyecto web
CUÁNDO_USAR: Al inicio de CADA nuevo proyecto

PASOS:
1. Analizar requerimientos y tipo de proyecto
2. Seleccionar arquetipo base (landing, ecommerce, saas, blog, portfolio)
3. Crear estructura de carpetas según global-rules.md
4. Inicializar repositorio Git con conventional commits
5. Configurar ESLint + Prettier + Husky
6. Instalar dependencias base según stack seleccionado
7. Crear archivo .env.example con variables necesarias
8. Configurar CI/CD básico (GitHub Actions)
9. Crear README.md template
10. Crear archivo DECISIONS.md vacío
11. Verificar instalación con 'npm run dev' o equivalente

OUTPUT_ESPERADO:
- Proyecto listo para desarrollo
- Git inicializado
- Linting y formateo configurados
- Documentación base creada

## WORKFLOW: /component-create
DESCRIPCIÓN: Crear nuevo componente siguiendo estándares
CUÁNDO_USAR: Al necesitar crear cualquier componente UI

PASOS:
1. Determinar nivel atómico: atom | molecule | organism | template | page
2. Crear carpeta en /components/[nivel]/NombreComponente/
3. Crear archivos:
   - index.tsx (o .vue) - Componente principal
   - NombreComponente.module.css o styled-components
   - NombreComponente.test.tsx - Tests
   - NombreComponente.stories.tsx - Storybook (si aplica)
   - types.ts - Tipos específicos del componente
4. Implementar siguiendo principios SOLID
5. Asegurar accesibilidad (ARIA, keyboard navigation)
6. Documentar props con JSDoc
7. Exportar en barrel file (index.ts de la carpeta padre)

REGLAS_ESPECÍFICAS:
- Máximo 200 líneas por archivo de componente
- Props interfaces siempre definidas y exportadas
- Default props para valores opcionales
- forwardRef para componentes que necesiten ref

## WORKFLOW: /responsive-check
DESCRIPCIÓN: Verificar responsive design en todos los breakpoints
CUÁNDO_USAR: Después de crear/modificar cualquier componente/layout

PASOS:
1. Identificar breakpoints del proyecto (sm, md, lg, xl, 2xl)
2. Verificar en cada breakpoint:
   - Layout no se rompe
   - Texto legible (tamaños adecuados)
   - Interacciones táctiles funcionan (touch targets &gt;= 44px)
   - No hay overflow horizontal
   - Imágenes se adaptan correctamente
3. Verificar orientación landscape en móviles
4. Verificar zoom hasta 200%
5. Documentar issues encontrados y soluciones
6. Capturar screenshots para referencia

OUTPUT:
- Reporte de compatibilidad responsive
- Screenshots de cada breakpoint
- Lista de fixes aplicados

## WORKFLOW: /performance-audit
DESCRIPCIÓN: Auditar performance del sitio
CUÁNDO_USAR: Antes de cada deploy a producción

PASOS:
1. Ejecutar Lighthouse en modo incógnito
2. Verificar Core Web Vitals:
   - LCP (Largest Contentful Paint)
   - FID (First Input Delay) o INP (Interaction to Next Paint)
   - CLS (Cumulative Layout Shift)
3. Analizar bundle con webpack-bundle-analyzer
4. Identificar JavaScript no utilizado (Coverage tab)
5. Optimizar imágenes si es necesario
6. Verificar estrategia de carga de fuentes
7. Implementar lazy loading donde falte
8. Re-ejecutar Lighthouse y comparar

META: Score &gt;= 90 en Performance, Accessibility, Best Practices, SEO

## WORKFLOW: /seo-optimize
DESCRIPCIÓN: Optimizar SEO técnico de la página
CUÁNDO_USAR: Antes de lanzar o al modificar contenido importante

PASOS:
1. Verificar títulos únicos y descripciones (&lt; 60 y &lt; 160 chars)
2. Implementar Open Graph tags (og:title, og:description, og:image)
3. Verificar estructura de headings (H1 único, jerarquía correcta)
4. Implementar JSON-LD structured data relevante
5. Verificar alt text en todas las imágenes
6. Crear/actualizar sitemap.xml
7. Verificar robots.txt
8. Implementar canonical URLs
9. Verificar URLs amigables
10. Testear con Google Rich Results Test

## WORKFLOW: /accessibility-audit
DESCRIPCIÓN: Auditar accesibilidad completa
CUÁNDO_USAR: Antes de lanzar y mensualmente

PASOS:
1. Ejecutar axe DevTools o Lighthouse A11y
2. Navegar con solo teclado (Tab, Enter, Escape, Flechas)
3. Activar VoiceOver/NVDA y navegar la página
4. Verificar contraste con WebAIM Contrast Checker
5. Verificar focus visible en todos los elementos interactivos
6. Verificar skip links si aplica
7. Validar HTML con W3C Validator
8. Verificar reducción de movimiento (prefers-reduced-motion)
9. Verificar modo oscuro si aplica (prefers-color-scheme)

META: 0 errores de accesibilidad críticos, WCAG 2.1 AA

## WORKFLOW: /security-check
DESCRIPCIÓN: Verificar seguridad básica
CUÁNDO_USAR: Antes de deploy y al agregar forms/inputs

PASOS:
1. Verificar no hay secrets en código (grep API keys, passwords)
2. Validar inputs de usuario (length, type, sanitization)
3. Verificar headers de seguridad (CSP, X-Frame-Options, etc.)
4. Revisar dependencias con 'npm audit'
5. Verificar HTTPS en todos los recursos externos
6. Verificar protección CSRF en forms
7. Revisar permisos de CORS

## WORKFLOW: /pre-deploy
DESCRIPCIÓN: Checklist final antes de deploy
CUÁNDO_USAR: Siempre antes de deploy a producción

PASOS:
1. Ejecutar /performance-audit
2. Ejecutar /accessibility-audit
3. Ejecutar /seo-optimize
4. Ejecutar /security-check
5. Verificar todas las variables de entorno en producción
6. Ejecutar test suite completo
7. Build de producción sin errores
8. Verificar no hay console.logs o debuggers
9. Revisar CHANGELOG.md actualizado
10. Crear tag de versión si aplica (semantic versioning)

## WORKFLOW: /documentation-update
DESCRIPCIÓN: Mantener documentación al día
CUÁNDO_USAR: Al finalizar features importantes o semanalmente

PASOS:
1. Actualizar README.md si cambió instalación o estructura
2. Documentar nuevos componentes en Storybook
3. Actualizar DECISIONS.md con decisiones arquitectónicas recientes
4. Actualizar CHANGELOG.md siguiendo Keep a Changelog
5. Verificar JSDoc está actualizado
6. Crear/actualizar diagramas de arquitectura si aplica