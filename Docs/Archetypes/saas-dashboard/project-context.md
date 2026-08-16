# SAAS DASHBOARD - Project Context Template

## IDENTIDAD DEL PROYECTO
- **Nombre:** [Nombre del SaaS]
- **Categoría:** [Analytics, CRM, Project Management, etc.]
- **Target:** [Startups / Enterprise / Freelancers]
- **Modelo de precios:** [Freemium / Tiered / Usage-based]

## ARQUITECTURA DE DATOS
- **Entidades principales:** [Users, Projects, Tasks, etc.]
- **Datos en tiempo real:** [Sí/No - WebSockets]
- **Reportes/Export:** [PDF, CSV, Excel]
- **Integraciones:** [Slack, Zapier, API webhooks]

## PÁGINAS/VISTAS REQUERIDAS
1. **Dashboard:** KPIs, charts, activity feed, quick actions
2. **List Views:** Tablas con filtros avanzados, bulk actions
3. **Detail Views:** Información completa, tabs, edit inline
4. **Settings:** Perfil, equipo, billing, notificaciones, API keys
5. **Onboarding:** Checklist primeros pasos

## ROLES Y PERMISOS
- **Admin:** Full access
- **Manager:** Team management, reports
- **User:** Operativo, solo sus datos
- **Viewer:** Solo lectura

## FUNCIONALIDADES CRÍTICAS
- [ ] Dark mode por defecto
- [ ] Keyboard shortcuts (Cmd+K command palette)
- [ ] Real-time updates (colaboración)
- [ ] Offline support (PWA)
- [ ] CSV import/export
- [ ] API documentation
- [ ] Webhook configuration

## STACK TECNOLÓGICO
- Framework: Next.js 15 (App Router)
- State: Zustand + TanStack Query
- UI: Shadcn/ui + Tailwind
- Charts: Tremor / Recharts
- Tables: TanStack Table v8
- Auth: Clerk (SSO, MFA, orgs)
- Database: PostgreSQL (Supabase/Neon)
- Realtime: Supabase Realtime
- Deploy: Vercel

## KPIs A MEDIR
- Time to first value: &lt;5 min
- Feature adoption rate: &gt;40%
- Churn rate: &lt;5% mensual
- NPS score: &gt;50

## NOTAS ESPECIALES
- [ ] Accessibility WCAG 2.1 AA mínimo
- [ ] Audit logs para compliance
- [ ] Data residency (GDPR)
- [ ] Sandbox environment