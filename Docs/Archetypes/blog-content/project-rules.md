# REGLAS ESPECÍFICAS - BLOG/CONTENT SITE
# Extensión de global-rules.md

## 1. ESTRUCTURA ESPECÍFICA

CONTENT_ARCHITECTURE:
  - Home: Featured posts, categorías, newsletter signup
  - Category Pages: Listado por tema con descripción
  - Post Detail: Contenido rico, autor, related posts, comentarios
  - Author Pages: Bio, foto, posts del autor, redes
  - Tag Pages: Nube de tags o listado por tag
  - Search: Búsqueda full-text de contenido
  - Archive: Por fecha (año/mes)

## 2. CONTENIDO Y EDITORIAL

CONTENT_RULES:
- Tipografía optimizada para lectura larga (line-height 1.6-1.8)
- Ancho de línea óptimo: 60-75 caracteres (~700px máximo)
- Imágenes destacadas (featured images) en cada post
- Subtítulos descriptivos cada 300-400 palabras
- Listas, blockquotes, código: Visual hierarchy clara
- Tabla de contenidos (TOC) sticky para posts largos (&gt;1500 palabras)
- Reading time estimation
- Series/colecciones de posts relacionados
- Content upgrade (lead magnet) dentro de posts populares

## 3. SEO DE CONTENIDO

CONTENT_SEO:
- URL slug optimizado (keywords, corto, descriptivo)
- Meta description que invite al click (call-to-action implícito)
- Open Graph images automáticas (1200x630px)
- Structured data: Article, Author, BreadcrumbList
- Internal linking: 3-5 links a posts relacionados por artículo
- External links: Abrir en nueva pestaña, nofollow si es paid
- Image alt text descriptivo (SEO + accesibilidad)
- Canonical URLs para evitar duplicate content
- RSS/Atom feed disponible

## 4. ENGAGEMENT

ENGAGEMENT_RULES:
- Newsletter signup prominente (popup controlado o inline)
- Related posts al final (basado en tags/categoría, no solo recientes)
- Compartir en redes sociales (buttons con contadores si aplica)
- Comentarios: Disqus, Giscus (GitHub), o custom
- Reacciones simples (like, clap) sin necesidad de comentar
- "Star" o bookmark para guardar (requiere auth)
- Progress bar de lectura (opcional)

## 5. PERFORMANCE DE CONTENIDO

CONTENT_PERFORMANCE:
- Lazy loading de imágenes en posts largos
- Preload de fuentes críticas para lectura
- Caching agresivo (contenido estático cambia poco)
- CDN para assets (Cloudflare o similar)
- Optimización de imágenes: WebP, responsive sizes
- Font subsetting (solo caracteres necesarios)