# User Flow Map

**Single source of truth for all user flows in the application.**

Use this document to understand each flow's steps, branching conditions, role restrictions,
and API contracts before writing or reviewing E2E tests. Flow ids map 1:1 to
`frontend/e2e/flow-definitions.json` (v2.4.1) and to the founding-artifact flow ids
(A1…F1) planned in `docs/plan/01-alcance-mvp.md`.

**Version:** 2.4.1
**Last Updated:** 2026-10-08

> Maintenance rule (docs/plan/09 DoD #4): each vertical iteration rewrites the sheets of the
> flows it ships and flips them from *Planned* to *Implemented*. Acceptance criteria live in
> `docs/plan/01-alcance-mvp.md`; this map records the concrete routes/endpoints as built.

---

## Table of Contents

1. [Module Index](#module-index)
2. [Home Module](#home-module)
3. [Auth Module](#auth-module)
4. [Planned Versiona Modules](#planned-versiona-modules)
5. [Cross-Reference](#cross-reference)
6. [Roles and Conventions](#roles-and-conventions)
7. [Projects — interactions by role](#projects--interactions-by-role)
8. [Document and review — interactions by role](#document-and-review--interactions-by-role)
9. [Shared navigation and public comparison](#shared-navigation-and-public-comparison)
10. [E2E Coverage Index](#e2e-coverage-index)

---

## Module Index

> **Status governance (updated 2026-10-08)**: the authoritative registry is
> `frontend/e2e/flow-definitions.json` (v2.4.1, 40 flows). Implementation, authored
> specs and executed coverage are separate: qualifying tests and their live/CI
> artifacts determine coverage. A row in this map never grants it by itself.

| Flow ID | Name | Module | Priority | Roles | Frontend Route | Status |
|---------|------|--------|----------|-------|----------------|--------|
| `home-loads` | Landing page loads | home | P1 | shared | `/` | Implemented |
| `auth-sign-in-form` | Sign-in + admisión TOTP | auth | P2 | shared | `/sign-in` | Implemented |
| `auth-sign-up-form` | Sign-up + desafío TOTP de Google | auth | P1 | shared | `/sign-up` | Implemented |
| `auth-login-invalid` | Invalid credentials rejected | auth | P1 | shared | `/sign-in` | Implemented |
| `auth-protected-redirect` | Protected routes redirect | auth | P1 | guest | `/dashboard` | Implemented |
| `auth-forgot-password-form` | Password recovery | auth | P2 | shared | `/forgot-password` | Implemented |
| `auth-sign-in-success` | Sign-in happy path (real session) | auth | P1 | shared | `/sign-in` → `/projects` (direct, It9) | Implemented (It1) |
| `auth-sign-out` | Sign out ends the session | auth | P2 | user | header (Salir) | Implemented (It1) |
| `auth-admin-login-handoff` | Django admin impersonation handoff | auth | P3 | staff | `/admin-login` | Implemented — spec added 2026-07-22 |
| `help-manual-browse` | Browse the interactive help | home | P3 | shared | `/manual` | Implemented — spec added 2026-07-22 |
| `a1-onboarding-wow` | A1 Sign-up and first wow | onboarding | P1 | guest | `/onboarding` | Implemented (It6) |
| `a2-invite-team` | A2 Invite team and roles | org | P1 | admin | `/projects/[id]/settings`, `/invite/[token]` | Implemented (It6) |
| `b1-create-project` | B1 Create a project | projects | P1 | editor | `/projects/new` | Implemented (It1) |
| `b2-projects-board` | B2 Projects board | projects | P2 | viewer | `/projects` | Implemented (It5; minimal list in It1) |
| `b3-project-settings` | B3 Project configuration | projects | P2 | admin | `/projects/[id]/settings` | Implemented (It5) |
| `c1-upload-first` | C1 Upload first document | documents | P1 | editor | `/projects/[id]` | Implemented (It1; upload-intent quota reviewed 2026-10-02) |
| `c2-upload-version` | C2 Upload a new version | documents | P1 | editor | `/projects/[id]/documents/[docId]` | Implemented (It1; upload-intent quota reviewed 2026-10-02) |
| `c3-history` | C3 Version history | documents | P2 | viewer | `/projects/[id]/documents/[docId]` | Implemented (It1) |
| `d1-request-review` | D1 Request a review | review | P1 | editor/reviewer | version viewer + `/inbox` | Implemented (It4) |
| `d2-assisted-review` | D2 Assisted review | review | P1 | reviewer | version viewer, auto (`ReviewContextBar`, shown when you sealed an earlier version) | Implemented (It4) |
| `d3-anchored-observations` | D3 Anchored observations | review | P1 | viewer/reviewer/editor/admin | version viewer | Implemented (It4; progressive reading reviewed 2026-10-02) |
| `d4-seal-approve` | D4 Approve with a seal | review | P1 | reviewer | version viewer (Seals panel) | Implemented (It3) |
| `d5-selective-invalidation` | D5 Selective invalidation | review | P1 | editor/reviewer/admin | seals panel + `/inbox` | Implemented (It3) |
| `e1-compare` | E1 Compare two versions | compare | P1 | viewer | `.../compare/[base]/[target]` | Implemented (It2) |
| `e3-configurable-checks` | E3 Configurable checks | compare | P2 | admin | `/projects/[id]/settings` + version viewer (Checks panel) | Implemented (It5) |
| `f1-billing` | F1 Plan limits + upgrade path (contact) | billing | P2 | owner | 402 sites → UpgradeDialog → `/precios` | Implemented (It7/It9 — no online checkout) |
| `f2-usage-panel` | F2 Usage panel + warnings + trial line | billing | P2 | member | `/org/usage` (header "Plan y uso") | Implemented (It7/It9) |
| `c4-delete-draft` | C4 Delete a draft version | documents | P2 | editor | version timeline | Implemented (It1) |
| `b4-archive-delete` | B4 Archive/delete a project | projects | P2 | admin | project settings + `/org/trash` | Implemented (It1) |
| `a3-account-security` | A3 TOTP, admisión y sesiones | auth | P2 | user | `/settings`, `/sign-in`, `/sign-up` | Implemented (It6) |
| `e2-saved-comparisons` | E2 Saved comparisons | compare | P2 | viewer | compare view + project panel | Implemented (It7) |
| `e4-constancia` | E4 Exportable certificate | review | P2 | admin | version viewer (Certificates panel — Constancias) | Implemented (It7) |
| `master-e2e-journey` | Master journey (16 steps, 3 users) | master | P1 | guest/editor/reviewer | end-to-end | Implemented (It8) |
| `public-pricing` | Public pricing page | billing | P1 | guest | `/precios` | Implemented (It9) |
| `trial-visibility` | Trial banner + days left | billing | P2 | user | global banner + `/org/usage` | Implemented (It9) |
| `public-compare` | Anonymous public PDF comparison | public | P1 | guest | `/comparar` → `/comparar/[id]` | Implemented (It9) |
| `layout-public-navigation` | Public navigation at every reference width | home | P1 | guest | public header | Implemented — owner spec: public/public-navigation |
| `layout-authenticated-navigation` | Authenticated navigation at every reference width | org | P1 | owner/admin/member | authenticated header | Implemented — owner spec: app/layout/authenticated-navigation |
| `public-compare-lifecycle` | Public comparison loading follows current page | public | P1 | guest | `/comparar/[id]` → `/comparar` → `/comparar/[id]` | Implemented — owner spec: public/public-compare-lifecycle |
| `f3-org-audit` | F3 Org audit log + CSV export | org | P2 | owner/admin | `/org/audit` | Implemented (It7) — spec added 2026-07-22 |

---

## Home Module

### home-loads

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Roles** | shared |
| **Frontend route** | `/` |
| **API endpoints** | none (static landing) + `GET /api/staging-banner/` (global gate) |

**Preconditions:** none.

**Steps:** open the root URL → the headline "El Git de tus documentos" and the sign-up CTA
are visible.

**Spec:** `e2e/public/smoke.spec.ts` (`@flow:home-loads`).

---

## Auth Module

Auth pages are inherited from the template and already functional (JWT + Google + reCAPTCHA).

### auth-sign-in-form / auth-login-invalid / auth-sign-in-success

| Field | Value |
|-------|-------|
| **Priority** | P2 / P1 / P1 |
| **Roles** | shared |
| **Frontend route** | `/sign-in` |
| **API endpoints** | `POST /api/sign_in/`, `POST /api/sign_in/2fa/`, `POST /api/google_login/`, `GET /api/google-captcha/site-key/` |

**Pasos:** el formulario muestra email, contraseña y recuperación. Credenciales inválidas o una cuenta inactiva muestran un error inline y no crean sesión. Una cuenta válida sin TOTP recibe tokens y aterriza directamente en `/projects`; una cuenta válida con TOTP pasa al desafío de código y sólo al completarlo recibe tokens. El desafío también puede seguir a una primera autenticación Google validada, pero el intercambio OAuth real sigue excluido de E2E por ser un proveedor externo (`docs/audit/03-mapa-flujos.md:489`).

Los claims de Google se validan en backend antes de buscar o crear una cuenta: audiencia configurada, email y `email_verified`. Un `202` debe traer `requires_2fa: true` y un desafío no vacío; una respuesta malformada conserva al visitante sin sesión y muestra el error de autenticación.

| Clase | Interacción observable | Cobertura |
|---|---|---|
| success | Contraseña válida sin TOTP crea cookies y llega a `/projects`. | `e2e/auth/session.spec.ts` (`auth-sign-in-success`) |
| error | Credenciales erróneas, cuenta inactiva, código TOTP erróneo o desafío inválido conservan la pantalla sin sesión. | A3 E2E para código; backend/unit para admisión y ciclo de desafío |
| failure | n/a como estado de UI separado: la falla de proveedor se normaliza a rechazo de autenticación y usa la misma superficie inline. | backend/unit |
| display | Se ve el formulario inicial y, después de un `202` válido, el de código TOTP. | `e2e/auth/auth.spec.ts` requiere revisión de navegación UI para crédito display |

**Spec:** `e2e/auth/auth.spec.ts` y `e2e/auth/session.spec.ts`.

### auth-sign-up-form

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Roles** | shared |
| **Frontend route** | `/sign-up` |
| **API endpoints** | `POST /api/sign_up/`, `POST /api/google_login/`, `POST /api/sign_in/2fa/` |

**Pasos:** el formulario renderiza y valida localmente la confirmación de contraseña. Un registro con contraseña válido recibe tokens y aterriza en onboarding. Si una cuenta existente que entra por Google ya tiene TOTP activo, el `202` válido reemplaza el formulario por el desafío de código; el código correcto aterriza en `/onboarding` y uno inválido conserva el desafío con su error inline.

La rama Google no recibe crédito E2E: depende de OAuth externo y se cubre en backend y frontend-unit. La rama password sigue cubierta por `e2e/auth/auth.spec.ts`; el desafío de Google se prueba en la capa unitaria, sin presentar un mock del proveedor como E2E real.

La política del servidor también rechaza contraseñas comunes y conserva el
formulario de registro con su error. El escenario E2E usa una dirección única y
`password123`, comprueba el mensaje real y que permanece en `/sign-up`.

### a3-account-security

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Roles** | user para enrolamiento y sesiones; shared al completar inicio de sesión |
| **Frontend routes** | `/settings`, `/sign-in`, `/sign-up` |
| **API endpoints** | `GET /api/me/security/`, `POST /api/me/2fa/setup/`, `POST /api/me/2fa/enable/`, `POST /api/sign_in/2fa/`, `GET/POST /api/me/sessions/…` |

**Pasos:** una persona autenticada activa TOTP desde Seguridad, confirma el código y guarda los códigos de respaldo. En un inicio posterior, una cuenta con TOTP activo recibe un desafío breve tras una primera autenticación válida. El código correcto crea la sesión; un código incorrecto o un desafío malformado, vencido, de usuario eliminado/inactivo o con TOTP ya desactivado devuelve 401 y no crea sesión.

| Clase | Interacción observable | Cobertura |
|---|---|---|
| success | Activar TOTP, salir, completar contraseña → desafío → código correcto y volver autenticado. | `e2e/app/onboarding/a3-account-security.spec.ts` |
| error | Código incorrecto muestra alerta y no crea sesión. El ciclo de desafío inválido se cubre en backend. | A3 E2E + pruebas backend |
| failure | n/a como superficie separada: el cliente presenta las fallas de endpoint en el mismo error del desafío. | frontend-unit/backend |
| display | Seguridad muestra el estado; login o registro muestran el desafío sólo después del `202` válido. | Selectores `security-section`, `twofa-step`, `twofa-code`, `twofa-verify` |

La autenticación Google real permanece exenta de E2E; la ruta password → desafío → código sí es una interacción de navegador real.

### auth-protected-redirect

| Field | Value |
|-------|-------|
| **Priority** | P1 |
| **Roles** | guest |
| **Frontend route** | `/dashboard` (guard: `proxy.ts`) |
| **API endpoints** | — |

**Steps:** anonymous visit to a protected route → redirect to `/sign-in?next=`. Today this is
a double hop and the spec pins both legs: `/dashboard` itself hard-redirects to `/projects`
(`app/dashboard/page.tsx` is now a bare `redirect('/projects')` stub), and the
`useRequireAuth` guard gating `/projects` then bounces the unauthenticated visitor to
`/sign-in` before `projects-grid` ever mounts.

**Spec:** `e2e/auth/auth.spec.ts`.

### auth-forgot-password-form

| Field | Value |
|-------|-------|
| **Priority** | P2 |
| **Roles** | shared |
| **Frontend route** | `/forgot-password` |
| **API endpoints** | `POST /api/send_passcode/`, `POST /api/verify_passcode_and_reset_password/` |

**Steps:** two-step form → request 6-digit code (valid 15 min) → verify code + set new
password.

| Clase | Interacción observable | Cobertura |
|---|---|---|
| display | Desde acceso, abrir recuperación y ver el formulario de correo. | `e2e/auth/auth.spec.ts` |
| error | Pedir código real por correo, rechazar una contraseña numérica y reintentar con el mismo código y una contraseña válida; comprobar el acceso posterior. | `e2e/auth/auth.spec.ts` |
| success | El reintento válido es la prueba de conservación del código del escenario de rechazo; no se declara una cobertura independiente de éxito. | Escenario anterior |
| failure | Fallos de transporte conservan el formulario; se prueban en frontend-unit y quedan fuera de la validación de política de esta ronda. | `app/forgot-password/__tests__/page.test.tsx` |

**Spec:** `e2e/auth/auth.spec.ts`.

---

## Planned Versiona Modules

> **Nota de análisis:** los checkpoints de reintento del engine son privados. El polling sigue exponiendo el mismo contrato público (`status`, `error`, `result`) y `result` permanece `null` hasta `done`; por eso no cambia ninguna interacción ni outcome de C1/C2.

The 16 MVP flows (A1…F1) are specified with Given/When/Then acceptance criteria in
`docs/plan/01-alcance-mvp.md`, their screens in `docs/plan/04-frontend.md` §2, their API in
`docs/plan/03-backend.md` §3, and their E2E designs (including the D5 queen test) in
`docs/plan/06-pruebas.md` §5. Each sheet is written into this map by the iteration that ships
it (see the Module Index status column for the shipping iteration).

---

## Cross-Reference

| Artifact flow | flow-definitions id | Ships in | E2E spec (actual path, verified 2026-08-13) |
|---|---|---|---|
| A1 | `a1-onboarding-wow` | It6 | `e2e/app/onboarding/a1-onboarding-wow.spec.ts` |
| A2 | `a2-invite-team` | It6 | `e2e/app/onboarding/a2-invite-team.spec.ts` |
| B1 | `b1-create-project` | It1 | `e2e/app/projects/b1-create-project.spec.ts` |
| B2 | `b2-projects-board` | It5 | `e2e/app/projects/b2-board-search.spec.ts` |
| B3 | `b3-project-settings` | It5 | `e2e/app/projects/b3-e3-governance.spec.ts` (shared with E3) |
| C1 | `c1-upload-first` | It1 | `e2e/app/documents/c1-upload-first-document.spec.ts` |
| C2 | `c2-upload-version` | It1 | `e2e/app/documents/c2-upload-new-version.spec.ts` |
| C3 | `c3-history` | It1 | `e2e/app/documents/c3-version-history.spec.ts` |
| D1 | `d1-request-review` | It4 | `e2e/app/reviews/d1-request-review.spec.ts` |
| D2 | `d2-assisted-review` | It4 | `e2e/app/reviews/d2-assisted-review.spec.ts` |
| D3 | `d3-anchored-observations` | It4 | `e2e/app/reviews/d3-anchored-observations.spec.ts` |
| D4 | `d4-seal-approve` | It3 | `e2e/app/seals/d4-seal-approve.spec.ts` |
| D5 | `d5-selective-invalidation` | It3 | `e2e/app/seals/d5-selective-invalidation.spec.ts`, `e2e/app/seals/d5-coordinator-confirmation.spec.ts` |
| E1 | `e1-compare` | It2 | `e2e/app/compare/e1-compare-versions.spec.ts` |
| E3 | `e3-configurable-checks` | It5 | `e2e/app/projects/b3-e3-governance.spec.ts` (shared with B3) |
| F1 | `f1-billing` | It7 | `e2e/app/billing/f1-f2-limits-usage.spec.ts` (shared with F2) |

> This table previously listed the file names proposed at MVP-planning time
> (`docs/plan/06` §5), before implementation chose its own directory layout
> (`e2e/app/<module>/...`) and, in three cases, folded two flow ids into one spec
> file (B3+E3, F1+F2, and separately E4+E2 in `e4-e2-certificate-saved.spec.ts`).
> Every path above was confirmed against `find frontend/e2e -name "*.spec.ts"` and the
> `@flow:` tag constants in `frontend/e2e/helpers/flow-tags.ts` on 2026-08-13.

## Roles and Conventions

Las superficies de admisión TOTP tienen selectores estables: `twofa-step`, `twofa-code`, `twofa-verify` y `security-section`. Permiten probar la rama real password → desafío → código. Un mock del proveedor Google no concede crédito E2E.

Viewer consulta proyectos y documentos; editor también crea proyectos; admin del
proyecto configura checks y administra invitaciones. Los permisos siguen las
reglas existentes del backend. Esta ronda cambia la presentación de proyectos,
sin agregar rutas ni acciones.

Las pruebas usan `data-testid` o roles accesibles y los tags `@flow` / `@outcome`
existentes. Una prueba de display debe navegar por la UI y comprobar datos de la
fixture. Los tamaños de `docs/RESPONSIVE_STANDARDS.md` son portrait primero
(835×1194), compact (412×915), landscape (1195×835), desktop (1440×900) y wide
(2560×1440). En compact se miden los controles de proyectos: el Header compartido
mantiene un desborde previo registrado fuera del alcance de este módulo.

## Projects — interactions by role

### Viewer

| Ruta / flujo | Interacción | Outcome | Resultado observable |
|---|---|---|---|
| `/projects` — B2 | Navegar mediante Panel, buscar un nombre y elegir Active | display | Aparece exactamente la tarjeta buscada; títulos y descripciones completos; filtro, búsqueda y creación caben en compact |

El tablero permite buscar y filtrar; la validación al crear corresponde a B1 y
los fallos del servidor al guardar configuración corresponden a B3.

### Editor

| Ruta / flujo | Interacción | Outcome | Resultado observable |
|---|---|---|---|
| `/projects/new` — B1 | Abrir Nuevo proyecto, completar un nombre y enviar | success | Se abre el detalle con el nombre creado |
| `/projects/new` — B1 | Enviar un nombre inválido | error | La validación conserva el formulario y no crea un proyecto |

### Admin del proyecto

| Ruta / flujo | Interacción | Outcome | Resultado observable |
|---|---|---|---|
| `/projects/[id]/settings` — B3 | Abrir ajustes desde el detalle, agregar/editar un check, guardar y recargar | success | Se confirma una nueva versión de configuración; persiste la etiqueta editada; campos y acciones admiten uso táctil en portrait |
| `/projects/[id]/settings` — B3 | Intentar guardar cuando falla el servidor | failure | Se muestra el error y sigue disponible el formulario sin guardar |
| `/projects/[id]/settings` — A2 | Abrir ajustes, completar el correo y elegir un rol | display | Los correos completos de miembros e invitaciones se ajustan al ancho portrait; Enviar y Revocar siguen accesibles |
| `/projects/[id]/settings` — A2 | Enviar una invitación válida | success | Aparece pendiente con correo y rol elegidos; al aceptarla se abre el proyecto |
| `/projects/[id]/settings` — A2 | Intentar invitar sin permiso | error | El servidor rechaza el intento sin crear la invitación |

## Document and review — interactions by role

### Editor — C1/C2 upload intent

| Flujo | Interacción | Outcome | Resultado observable |
|---|---|---|---|
| C1/C2 | Solicitar un upload dentro de la cuota, elegir un PDF válido y completarlo. | success | Se emite la URL firmada y la versión pasa al análisis. |
| C1/C2 | Elegir un PDF inválido o protegido. | error | El formulario conserva el borrador y muestra el error. |
| C1/C2 | Solicitar otra intención después de consumir 20 en una hora con el mismo usuario. | failure | Aparece el 429 reintentable, sin URL nueva; una intención anterior puede completarse. |

La cuota pertenece al usuario autenticado, no al documento ni al navegador. La
validación real del límite corresponde a los tests backend con caché aislada; las
pruebas de UI verifican la presentación del 429. La preparación masiva de E2E usa
una cuota finita mayor, exclusivamente en su entorno de pruebas.

### Viewer, reviewer, editor y admin — D3 anchored observations

| Interacción | Outcome | Resultado observable |
|---|---|---|
| Reviewer o admin crea un hilo anclado; editor responde; el autor o admin resuelve y el autor reabre. | success | El resumen refleja el estado I14 sin descargar toda la conversación. |
| Editor envía una respuesta vacía. | error | Aparece la validación y el hilo sigue abierto. |
| Abrir el panel desde la historia del documento, cargar más hilos, respuestas anteriores, historial, una versión histórica o el siguiente fragmento de texto/ancla. | display | Se ven texto, estado, autor, página y metadatos de la fixture; cada control carga únicamente la página o fragmento solicitado. |
| Falla una petición de lista, respuestas, historial o contenido; pulsar reintentar. | failure | Los datos visibles se conservan, aparece un aviso y se reintenta sólo la petición fallida. |
| Cambiar versión, filtro de resueltas o hilo seleccionado con una petición pendiente. | display | Se muestra únicamente el alcance actual; la respuesta obsoleta no lo reemplaza. |

El enlace histórico mantiene el hilo mediante `?observation=UUID`, incluso fuera
de la primera página. Las anclas de versiones en la papelera conservan sus datos
sin ofrecer un enlace al visor que respondería 404.

Selectores D3: `observations-panel`, `show-resolved`, `add-observation`,
`observations-more`, `observations-retry`, `observation-<id>`,
`observation-text-<id>-more`, `observation-replies-<id>`,
`observation-replies-more-<id>`, `observation-history-<id>`,
`observation-history-more-<id>`, `observation-anchor-<id>` y
`observation-anchor-more-<id>`.

## Shared navigation and public comparison

### Guest — public navigation (`layout-public-navigation`)

| Class | Interaction | Observable result |
|---|---|---|
| success | Open the menu on phone/portrait tablet, follow a link, change language; close with its button, Escape or outside click. | Same destinations and order as desktop; selected destination reached; closing returns focus. |
| display | Open the theme control and choose Dark. | Dark mode and the local preference change while navigation remains usable. |
| error | n/a: these local controls expose no validation or permission response. | Destination-page validation belongs to its owning flow. |
| failure | n/a: this component displays no asynchronous server failure. | Server outcomes belong to destination pages. |

Selectors: `public-header`, `public-nav-toggle`, `public-nav-menu`,
`locale-toggle`; accessible navigation/menu/link roles.

### Owner/admin/member — authenticated navigation (`layout-authenticated-navigation`)

| Class | Interaction | Observable result |
|---|---|---|
| success | Open the compact menu, follow Plan y uso or permitted Papelera, close it and sign out. | Same role-appropriate destinations at each width; only org owner/admin see Papelera; closing restores focus; sign-out removes the session. |
| display | Open the bell, inspect the notification and follow its link. | The concrete title/badge is visible, the notification is marked read and its destination is reached. |
| error | n/a: lack of org administration hides Papelera before an attempted header action. | Permission errors in the destination remain part of that page's flow. |
| failure | No observable header outcome: notification fetch/read failures are stored or treated as best effort. | Those branches require store/unit evidence rather than invented UI alerts. |

Selectors: `app-header`, `app-nav-toggle`, `app-nav-menu`, `notification-bell`,
`notification-badge`, `notification-dropdown`, `nav-plan-usage`.

### Guest — comparison lifecycle (`public-compare-lifecycle`)

| Class | Interaction | Observable result |
|---|---|---|
| success | Start comparison A, navigate through the header to another comparison, start B and let A settle late. | A is aborted; B's file names and result remain; stale success/failure cannot replace them. |
| error | Invalid uploads, OCR rejection and rate limiting belong to `public-compare`. | An obsolete error must be discarded; out-of-order errors are also tested at the unit layer. |
| failure | A current failed job/HTTP response/timeout belongs to `public-compare` failure. | Current failure shows the alert and offers a new comparison; it is distinct from ignoring a stale response. |
| display | No separate lifecycle interaction. | Processing/result data are assertions proving replacement succeeds. |

The page aborts on route cleanup; the store cancels the previous transport and
poll timer and protects publication with load identity. The browser lifecycle
spec controls only HTTP: form interaction, header navigation, cancellation and
rendering execute in the app. Navigation acceptance uses exactly 412×915,
835×1194, 1195×835, 1440×900 and 2560×1440. Geometry assertions supplement user
interactions and do not count as standalone coverage.

## E2E Coverage Index

| Flujo | Outcomes declarados | Spec dueño |
|---|---|---|
| B1 | success, error | `e2e/app/projects/b1-create-project.spec.ts` |
| B2 | display | `e2e/app/projects/b2-board-search.spec.ts` (compact + landscape) |
| B3 | success, failure | `e2e/app/projects/b3-e3-governance.spec.ts` (persistencia en portrait) |
| A2 | success, error, display | `e2e/app/onboarding/a2-invite-team.spec.ts` (correos largos en portrait) |
| C1 | success, error, failure | `e2e/app/documents/c1-upload-first-document.spec.ts` — presentación de cuota agotada |
| C2 | success, error, failure | `e2e/app/documents/c2-upload-new-version.spec.ts` — presentación de cuota agotada |
| D3 | success, error, failure, display | `e2e/app/reviews/d3-anchored-observations.spec.ts` — lectura progresiva, reintento e historial |

La auditoría automática calcula la cobertura real. Estas filas declaran qué se
debe validar; mencionar un spec aquí no le otorga crédito de cobertura.

### Owners added in the 2026-10-08 round

| Flow | Outcomes | Owning spec |
|---|---|---|
| `layout-public-navigation` | success, display | `e2e/public/public-navigation.spec.ts` |
| `layout-authenticated-navigation` | success, display | `e2e/app/layout/authenticated-navigation.spec.ts` |
| `public-compare-lifecycle` | success | `e2e/public/public-compare-lifecycle.spec.ts` |
| `public-compare` | success, error, failure | `e2e/public/public-compare.spec.ts` and the current-job failure case in `public-compare-lifecycle.spec.ts` |

Execution evidence belongs to the exact PR/integration commit artifacts, not the
presence of these rows. No unrelated route has been reclassified as mature.

## R2 — validación de D5 y PDF (2026-10-08)

| Vista | Interacción | Clase | Cobertura de esta ronda |
|---|---|---|---|
| Visor y sellos | Nueva entrega nativa conserva el sello original hasta v3 | success | D5-F06 en el E2E automático existente |
| Bandeja y plan D5 | Administrador confirma una entrega degradada; el revisor recibe el aviso posterior | success | D5-A04 y cadena D5 hasta v3 validados en la aplicación real en `97ea262`: dos casos, sin reintentos; la QA final corresponde al SHA combinado del reporte |
| Plan D5 | Administrador ve el plan pendiente, propuesta y evidencia | display | Observado dentro del recorrido de éxito; sin crédito E2E propio para display |
| Plan D5 | Si falla el POST de confirmación, el plan permanece y aparece el error | failure | Brecha E2E conservada fuera de la autoría aprobada de R2 |
| Plan D5 | Validación de elecciones en el formulario | error | n/a: cada sello pendiente llega con una elección válida preseleccionada; los rechazos de API se prueban en backend |
| Vista previa, visor y comparación | Subir el PDF y seleccionar una sección conserva contenido y resaltados al cambiar el ancho | display/success | C1/E1 en los cinco viewports del estándar |

La repetición concurrente, elecciones incompletas y proyectos archivados se
comprueban en API/servicios MySQL. No se adjudica cobertura E2E negativa por
esas pruebas. La sellabilidad estructural sigue pendiente y no recibe crédito
D5-L01 por el nuevo recorrido. Las ejecuciones efectivas y los gaps restantes
se acreditan en el reporte R2, no mediante el registro por sí solo.
Los dos specs D5 ejecutados llevan `@outcome:success`; no conceden crédito
cualificado a display ni failure. El registro declara ambos comportamientos
existentes para conservar visibles esas brechas, sin inventar pruebas ni ampliar
la implementación del producto.
