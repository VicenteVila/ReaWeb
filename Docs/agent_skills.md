# SKILLS DE AGENTES - UNIVERSAL WEB DEVELOPMENT
# Estas son las capacidades que todo agente debe dominar

## SKILL CATEGORY: Frontend Architecture
ID: frontend-arch
NIVEL: EXPERTO

SUBSKILLS:
  - react-advanced:
      - Hooks avanzados (useCallback, useMemo, useLayoutEffect)
      - Patrones: Compound Components, Render Props, HOCs
      - Performance optimization (React.memo, code splitting)
      - Server Components (Next.js App Router)
  
  - vue-advanced:
      - Composition API
      - Provide/Inject
      - Suspense y Async Components
      - Performance optimization
  
  - state-management:
      - Redux Toolkit / Zustand / Jotai (React)
      - Pinia (Vue)
      - React Query / SWR para server state
  
  - styling-architecture:
      - CSS-in-JS (Styled-components, Emotion)
      - CSS Modules
      - Utility-first (Tailwind CSS)
      - Design Systems (Storybook)
      - Variables CSS y temas dinámicos

## SKILL CATEGORY: Backend Integration
ID: backend-integration
NIVEL: AVANZADO

SUBSKILLS:
  - api-design:
      - RESTful APIs
      - GraphQL (queries, mutations, subscriptions)
      - tRPC para type-safe APIs
  
  - authentication:
      - JWT, OAuth 2.0, OpenID Connect
      - NextAuth.js / Auth.js
      - Clerk, Supabase Auth
      - RBAC (Role-Based Access Control)
  
  - database:
      - PostgreSQL básico
      - Prisma / Drizzle ORM
      - Supabase / Firebase
      - Redis para caching
  
  - serverless:
      - Vercel Functions
      - Netlify Functions
      - AWS Lambda básico

## SKILL CATEGORY: Performance Engineering
ID: performance
NIVEL: AVANZADO

SUBSKILLS:
  - core-web-vitals:
      - Optimización LCP (imágenes, fuentes, critical CSS)
      - Optimización INP/FID (JavaScript main thread)
      - Optimización CLS (dimensiones de imágenes, web fonts)
  
  - loading-strategies:
      - Lazy loading de imágenes y componentes
      - Prefetching y preloading
      - Service Workers y caching
      - Edge functions
  
  - bundle-optimization:
      - Tree shaking
      - Code splitting (dynamic imports)
      - Module Federation (micro-frontends)
      - Análisis de bundle

## SKILL CATEGORY: Accessibility (A11y)
ID: accessibility
NIVEL: EXPERTO (Obligatorio)

SUBSKILLS:
  - wcag-implementation:
      - Navegación por teclado completa
      - Screen reader optimization (ARIA)
      - Contraste y color
      - Focus management
      - Skip links y landmarks
  
  - testing-a11y:
      - axe-core
      - Lighthouse a11y audits
      - Testing con screen readers
  
  - inclusive-design:
      - prefers-reduced-motion
      - prefers-color-scheme
      - prefers-contrast
      - Responsive a zoom

## SKILL CATEGORY: SEO Technical
ID: seo-technical
NIVEL: AVANZADO

SUBSKILLS:
  - on-page-seo:
      - Meta tags dinámicos
      - Structured data (Schema.org)
      - Open Graph y Twitter Cards
      - Canonical URLs y hreflang
  
  - technical-seo:
      - Sitemaps dinámicos
      - robots.txt optimization
      - Core Web Vitals para SEO
      - JavaScript SEO (rendering)

## SKILL CATEGORY: DevOps & Deployment
ID: devops
NIVEL: INTERMEDIO-AVANZADO

SUBSKILLS:
  - ci-cd:
      - GitHub Actions
      - Vercel / Netlify deployments
      - Preview deployments
  
  - containerization:
      - Docker básico
      - Docker Compose
  
  - monitoring:
      - Vercel Analytics
      - Sentry para error tracking
      - LogRocket / Hotjar para session replay

## SKILL CATEGORY: Testing
ID: testing
NIVEL: AVANZADO

SUBSKILLS:
  - unit-testing:
      - Jest / Vitest
      - React Testing Library / Vue Test Utils
      - MSW (Mock Service Worker)
  
  - e2e-testing:
      - Playwright (preferido)
      - Cypress
  
  - visual-testing:
      - Chromatic / Storybook
      - Percy

## SKILL CATEGORY: Design Implementation
ID: design-implementation
NIVEL: AVANZADO

SUBSKILLS:
  - design-to-code:
      - Figma a código (autolayout, constraints)
      - Implementación pixel-perfect
      - Design tokens (Style Dictionary)
  
  - animation:
      - Framer Motion (React)
      - GSAP para animaciones complejas
      - CSS animations y transitions
      - Micro-interactions
  
  - responsive-design:
      - Mobile-first approach
      - Container queries
      - Fluid typography y spacing

## SKILL CATEGORY: Security
ID: security
NIVEL: AVANZADO

SUBSKILLS:
  - web-security:
      - OWASP Top 10 para web
      - CSP (Content Security Policy)
      - CORS configuración segura
      - Sanitización de inputs (DOMPurify)
  
  - auth-security:
      - JWT best practices
      - HttpOnly cookies
      - CSRF protection
      - Rate limiting

## SKILL CATEGORY: Content Management
ID: cms
NIVEL: INTERMEDIO

SUBSKILLS:
  - headless-cms:
      - Contentful
      - Sanity
      - Strapi
      - WordPress Headless (GraphQL)
  
  - i18n:
      - next-i18next / react-i18next
      - FormatJS / react-intl
      - RTL (Right-to-Left) layouts