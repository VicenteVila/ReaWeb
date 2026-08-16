# E-COMMERCE - Project Context Template

## IDENTIDAD DEL PROYECTO
- **Nombre tienda:** [Nombre]
- **Nicho:** [Moda, Electrónica, Hogar, etc.]
- **Modelo:** [Dropshipping, Stock propio, Marketplace]
- **Mercado:** [Local / Nacional / Internacional]

## CATÁLOGO
- **Número de productos:** [Cantidad aproximada]
- **Categorías principales:** [Lista]
- **Productos con variants:** [Talla, Color, etc.]
- **Rango de precios:** [$ - $$$]

## PÁGINAS REQUERIDAS
1. **Home:** Carrusel promos, categorías destacadas, bestsellers
2. **Category:** Filtros faceted, sorting, grid/list view
3. **Product:** Galería zoom, variants, reviews, related products
4. **Cart:** Mini-cart persistente, upsells, estimador envío
5. **Checkout:** Guest checkout, múltiples pagos, progress indicator
6. **Account:** Órdenes, direcciones, wishlist, reorders

## FUNCIONALIDADES CRÍTICAS
- [ ] Búsqueda instantánea (Algolia)
- [ ] Filtros en mobile (drawer)
- [ ] Cart abandonment emails
- [ ] Stock en tiempo real
- [ ] Reviews con fotos
- [ ] Wishlist persistente
- [ ] Multi-moneda (si internacional)

## DATOS REQUERIDOS
- **Pasarela de pago:** [Stripe / PayPal / MercadoPago]
- **Envíos:** [Proveedor / Tarifas / Zonas]
- **Impuestos:** [Automático / Manual]
- **Políticas:** [Returns / Shipping / Privacy URLs]

## STACK TECNOLÓGICO
- Framework: Next.js 15 + Shopify Hydrogen / Custom
- Database: PostgreSQL + Prisma
- Search: Algolia
- Payments: Stripe + PayPal
- CMS: Sanity para contenido
- Inventory: Shopify / Custom admin
- Deploy: Vercel Pro

## KPIs A MEDIR
- Conversion rate: &gt;2%
- AOV (Average Order Value): Objetivo $
- Cart abandonment: &lt;70%
- Checkout completion: &gt;60%

## NOTAS ESPECIALES
- [ ] PWA para mobile
- [ ] One-click checkout (Apple Pay / Google Pay)
- [ ] Live chat (Intercom/Tidio)
- [ ] Back-in-stock notifications