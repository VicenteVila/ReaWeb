# REGLAS ESPECÍFICAS - E-COMMERCE
# Extensión de global-rules.md

## 1. ESTRUCTURA ESPECÍFICA

ECOMMERCE_PAGES:
  - Home: Featured products, categorías, promociones
  - Category Page: Filtros, sorting, grid/list view, paginación
  - Product Detail: Galería, variants, precio, stock, reviews, related products
  - Cart: Resumen editable, upsells, estimador de envío
  - Checkout: Proceso multi-step o one-page, guest checkout
  - Account: Dashboard, órdenes, direcciones, wishlist
  - Search: Búsqueda con filtros, autocomplete, sugerencias

## 2. PRODUCTOS

PRODUCT_RULES:
- Imágenes: Mínimo 3 por producto (front, back, detail), zoom habilitado
- Variants: Selector visual de color/tamaño (no solo dropdown)
- Precios: Mostrar savings si hay discount, strikethrough en original
- Stock: Indicador claro (disponible, pocos, agotado)
- Reviews: Estrellas promedio prominente, reviews verificadas
- Breadcrumbs: Siempre visibles en navegación de categorías
- URL: /categoria/subcategoria/producto-slug

## 3. CARRO Y CHECKOUT

CART_CHECKOUT_RULES:
- Cart persistente (localStorage + backend si logged in)
- Mini-cart accesible desde cualquier página
- Guest checkout disponible (no forzar registro)
- Progress indicator en checkout multi-step
- Múltiples métodos de pago (Stripe, PayPal, MercadoPago según región)
- Cálculo de envío en tiempo real
- Order confirmation page con tracking number
- Abandoned cart recovery (emails automáticos)

## 4. PERFORMANCE Y SEO

ECOMMERCE_SEO:
- Structured data: Product, Offer, Review, BreadcrumbList
- Canonical URLs para productos con variants
- Sitemap dinámico con todos los productos
- Meta descriptions únicas por categoría y producto
- Rich snippets para precios y disponibilidad
- Internal linking: Productos relacionados, también compraron

## 5. SEGURIDAD Y CONFIANZA

TRUST_RULES:
- SSL en todo el sitio (obligatorio)
- Badges de seguridad en checkout (Norton, McAfee si aplica)
- Políticas claras: Returns, shipping, privacy
- Chat de soporte visible
- Teléfono de contacto visible
- Reviews de Trustpilot o Google Business integradas