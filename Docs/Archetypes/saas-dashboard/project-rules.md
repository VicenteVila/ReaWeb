# REGLAS ESPECÍFICAS - SaaS DASHBOARD
# Extensión de global-rules.md

## 1. ESTRUCTURA ESPECÍFICA

DASHBOARD_LAYOUT:
  - Sidebar Navigation: Iconos + labels, collapsible, nested items
  - Top Header: Search global, notifications, profile, breadcrumbs
  - Main Content Area: Dashboard widgets, tablas, forms
  - Contextual Side Panel: Detalles, edición rápida, help
  - Footer: Minimal o none (infinite scroll preferido)

DASHBOARD_PAGES:
  - Overview/Dashboard: KPIs, charts, activity feed, quick actions
  - Data Tables: Listados con filtros avanzados, sorting, bulk actions
  - Detail Views: Información completa de un registro, tabs
  - Settings: Perfil, equipo, billing, integraciones, notificaciones
  - Onboarding: Checklist de primeros pasos para nuevos usuarios

## 2. UX/UI ESPECÍFICO

DASHBOARD_UX_RULES:
- Empty states ilustradas y con CTA claro
- Loading states esqueletos (skeletons), no spinners genéricos
- Optimistic UI: Actualizar UI antes de confirmar backend
- Infinite scroll o paginación con tamaño configurable
- Bulk actions: Selección múltiple con acciones en toolbar
- Keyboard shortcuts: Power users (Ctrl/Cmd + K para command palette)
- Dark mode: Implementar siempre (preferencia del sistema por defecto)
- Responsive: Tablet ok, mobile como read-only o app nativa recomendada

## 3. DATOS Y ESTADO

DATA_MANAGEMENT:
- Real-time updates: WebSockets o Server-Sent Events para colaboración
- Caching strategy: React Query con stale-while-revalidate
- Optimistic updates para acciones frecuentes (like, delete, update)
- Undo functionality para acciones destructivas (toast con "Deshacer")
- Auto-save en forms largos (drafts locales)
- Export data: CSV, Excel, PDF según contexto

## 4. SEGURIDAD Y PERMISOS

AUTHZ_RULES:
- RBAC (Role-Based Access Control): Admin, Manager, User, Viewer
- Permission-based UI: Ocultar elementos no autorizados, no solo deshabilitar
- Audit logs: Quién hizo qué y cuándo (inmutable)
- 2FA obligatorio para admins
- Session management: Ver dispositivos activos, revoke access
- API keys: Generación, rotación, scopes limitados

## 5. PERFORMANCE

DASHBOARD_PERFORMANCE:
- Code splitting por ruta y por feature
- Virtualización para listas largas (&gt;100 items)
- Debounce en búsquedas (300ms)
- Throttle en scroll y resize events
- Web Workers para cálculos pesados
- Lazy load de charts y componentes pesados