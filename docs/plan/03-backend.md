# 03 — Backend

> Django app map, the DRF endpoint table (resource, method, required permission, flow served),
> the analysis/comparison engine as a queue-consumed service (contract summary — full spec in
> `05-motor-comparacion.md`), and the role/permission model mapped to endpoints. Data model
> and invariants (Ix) in `02-modelo-datos.md`.

## 1. Base reused

Kept from the template, as-is or minimally adapted:

- **Auth stack**: custom `User` (email login) + simplejwt, endpoints `sign_up/`, `sign_in/`,
  `google_login/`, `token/refresh/`, `validate_token/`, `send_passcode/`,
  `verify_passcode_and_reset_password/`, `update_password/`, reCAPTCHA, admin impersonation
  ("login as" → frontend handoff). `sign_up` is extended: it auto-creates the personal
  Organization and triggers the sample-project job (A1).
- **Conventions**: function-based views with `@api_view` + a `services/` layer holding all
  domain logic; triple serializers (List/Detail/CreateUpdate); explicit `path()` url modules
  composed per app under `/api/` (no versioning); settings split base/dev/prod driven by
  `.env`; pytest + factory-boy + freezegun test layout; `create_fake_data`/`delete_fake_data`
  management commands (rewritten for Versiona models); custom admin site; django-dbbackup;
  django-silk.

Justified deviations from the template (each solves a real gap):

| Deviation | Why |
|---|---|
| Parameterized DRF permission decorators instead of inline `is_staff` checks | Inline checks do not scale to 5 roles × 2 scopes × ~45 endpoints (see §5). |
| `DEFAULT_PAGINATION_CLASS` (PageNumberPagination, page_size 25) | The template returns unbounded lists. |
| Throttling scopes on auth, upload and webhooks | Public-facing abuse surface. |
| `public_id` (UUIDv7) in routes instead of integer PKs | Anti-enumeration in a multi-tenant product (I12). |
| Huey → **Celery** (+ django-celery-results, django-celery-beat) | Fixed mission decision; the template's four operational periodic tasks (weekly DB+media backup, Silk cleanups) migrate to beat unchanged. |
| **MySQL 8** (fleet standard; the project ran on PostgreSQL until 2026-08-03) | B2 search is MySQL FULLTEXT over Spanish-stemmed tokens built in `documents/search.py`. |
| FileSystemStorage → **django-storages S3/MinIO** for domain media | Fixed mission decision; `STORAGES['default']` is already the clean extension point. |

Removed: Blog/Product/Sale (models, serializers, views, urls, tests, fake-data subcommands),
`django_attachments` + `easy_thumbnails` (image-gallery oriented; PDF storage is a dedicated
`documents/services/storage_service.py`).

## 2. App map (bounded contexts)

Replaces the single-app monolith (`base_feature_app`). One line of responsibility each:

| App | Responsibility | Owns (models) |
|---|---|---|
| `core` | Shared mixins (`TimestampedModel`, `PublicIdModel`), default pagination, permission-decorator base, scoping helpers (`scoped_queryset`), StagingPhaseBanner. | StagingPhaseBanner |
| `accounts` | Template auth (sign-up/in, Google, reset, impersonation, captcha) + email verification (V2 wiring) + profile. | User, PasswordCode |
| `orgs` | Organizations, org memberships, invitations and acceptance (A1/A2). | Organization, OrganizationMembership, Invitation |
| `projects` | Projects, project memberships, versioned configuration and section owners (B1/B2/B3). | Project, ProjectMembership, ProjectConfigVersion, SectionOwnershipRule |
| `documents` | Documents, immutable versions, sections and stable identity, S3 storage service (C1/C2/C3). | Document, DocumentVersion, Section, SectionVersion, SectionLineage |
| `reviews` | Review requests, inbox, seals, validity chain, approval, D5 domain orchestration (D1/D2/D4/D5). | ReviewRequest, ReviewAssignment, Seal, SealSection, SealValidityRecord |
| `observations` | Anchored observations, threads, cross-version re-anchoring (D3). | Observation, ObservationAnchor, ObservationReply |
| `checks` | Check definitions (under pinned config), runs, results with evidence (E3). | CheckDefinition, CheckRun, CheckResult |
| `comparisons` | Comparisons between any two versions, per-section diffs (E1). | Comparison, SectionDiff |
| `engine` | The engine as a service: EngineJob, Celery tasks, PDF pipeline (PyMuPDF/OCR), matching — knows nothing about reviews/billing; extractable to a separate deployable later. | EngineJob |
| `notifications` | Notification model + **EmailTemplateRegistry** (new — replaces the template's f-string emails) + D5 selective delivery. | Notification |
| `billing` | Plans, subscriptions, limits, checkout, webhook, invoices (F1). | Plan, Subscription, PaymentEvent |
| `audit` | Append-only AuditEvent + `audit.record()` service called by every other service (base for F3). | AuditEvent |

Services per aggregate inside each app (template convention):
`version_service`, `storage_service`, `section_service`, `review_service`, `seal_service`,
`invalidation_service` (D5 pure core), `approval_service`, `observation_service`,
`check_service`, `comparison_service`, `billing_limits_service`, `notification_service`,
`audit.record`.

## 3. DRF endpoint table (MVP)

Prefix `/api/`. All list endpoints paginated (25). Routes use `public_id`. Permission column =
minimum **effective role** (§5); "—" = `AllowAny`. `⚙︎` = returns/relates to an async
EngineJob.

### Auth (template, kept)

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| POST | `sign_up/` · `sign_in/` · `google_login/` · `token/refresh/` · `send_passcode/` · `verify_passcode_and_reset_password/` | — | A1 | Throttled (5/min). `sign_up` auto-creates personal org + sample-project job ⚙︎. |
| GET | `validate_token/` | authenticated | A1 | Session restore for the SPA. |
| POST | `update_password/` | authenticated | A1 | |

### Organizations, members, invitations

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| GET | `orgs/` | authenticated | A1 | My orgs with my role. |
| POST | `orgs/` | authenticated | A2 | Create team org. |
| GET/PATCH | `orgs/{org}/` | org member / org admin | A2 | |
| GET | `orgs/{org}/members/` | org member | A2 | |
| PATCH/DELETE | `orgs/{org}/members/{user}/` | org admin | A2 | Role change / removal; ≥1 owner guard. |
| GET/POST | `orgs/{org}/invitations/` | org admin (project-scoped invite: project admin) | A2 | Seat limit (I13); sends email. |
| DELETE | `orgs/{org}/invitations/{id}/` | org admin | A2 | Revoke. |
| GET | `invitations/{token}/` | — | A2 | Public preview (org/project name, role). |
| POST | `invitations/accept/` | authenticated (token in body) | A2/A1 | Creates memberships; lands on the project. |

### Projects & configuration

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| GET | `orgs/{org}/projects/?q=&status=` | org member | B2 | Name search + derived-state filter, membership-scoped. |
| POST | `orgs/{org}/projects/` | org member | B1 | Creator becomes project admin; plan limit (I13) → 402/409. |
| GET | `search/documents/?org={org}&q=` | org member | B2 | FTS `spanish` over latest-version SectionVersions, membership-scoped. |
| GET/PATCH | `projects/{proj}/` | viewer / project admin | B1/B3 | |
| GET | `projects/{proj}/config/` | viewer | B3 | Current + history of ProjectConfigVersion. |
| PUT | `projects/{proj}/config/` | project admin | B3 | Creates a NEW ProjectConfigVersion (never edits; rules from next version — I8). |
| GET/POST | `projects/{proj}/members/` | project admin (GET: viewer) | A2 | |
| PATCH/DELETE | `projects/{proj}/members/{user}/` | project admin | A2 | |

### Documents, versions, upload & download

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| GET/POST | `projects/{proj}/documents/` | viewer / editor | C1 | POST creates the Document shell; v1 arrives via upload. |
| GET | `documents/{doc}/` | viewer | C3 | approved_version, latest, aggregate traffic light. |
| GET | `documents/{doc}/versions/` | viewer | C3 | Timeline; free plan: >30-day versions flagged `locked` (DP-04). |
| POST | `documents/{doc}/versions/upload_intent/` | editor | C1/C2 | Validates plan/size (I13, DP-11) → `{upload_id, presigned_put_url, headers}` (DP-06). Throttle 20/h. |
| POST | `documents/{doc}/versions/complete/` | editor | C1/C2 | `{upload_id, message}`: verifies object + magic bytes + full parse, computes sha256 (I9), rejects duplicate (F6), creates version (I1), enqueues analysis ⚙︎ → **202 {version_id, job_id}**. |
| GET | `versions/{ver}/` | viewer | C2/C3 | analysis_status, scenario, traffic light, D5 summary. |
| GET | `versions/{ver}/download/` | viewer | C3 | 302 → signed URL (TTL 5 min) + AuditEvent; blocked if `locked`. |
| GET | `versions/{ver}/sections/` | viewer | D2/D3 | With page ranges and normalized bboxes for the viewer. |
| GET | `versions/{ver}/checks/` | viewer | E3 | Results + evidence (page, reason). |
| GET | `versions/{ver}/seals/` | viewer | D4/D5 | Validity computed via I11 + validity records (constancias). |

### Comparisons

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| POST | `documents/{doc}/comparisons/` | viewer | E1 | `{from, to}` any pair; idempotent: 200 if cached, 202 ⚙︎ if not. |
| GET | `comparisons/{cmp}/` | viewer | E1/C2 | Feeds the three views: summary, section list, side-by-side refs. |
| GET | `comparisons/{cmp}/sections/{sec}/diff/` | viewer | E1 | Fine word diff (inline JSON < 256 KB or signed artifact URL). |

### Review, seals, D5

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| POST | `versions/{ver}/review_requests/` | editor | D1 | Auto-assigns via SectionOwnershipRule of the pinned config; selective notification. |
| GET | `review_requests/{id}/` | viewer | D1 | |
| GET | `me/review_inbox/` | authenticated | D1/D2/D5 | Assignments + re-reviews + pending coordinator confirmations. |
| GET | `review_requests/{id}/progress/` | assigned reviewer | D2 | "Already reviewed by you" per section (last seal vs changes). |
| POST | `versions/{ver}/seals/` | reviewer | D4 | `{covers_all | section_ids}`; guards I6/I9/I10; Ed25519 signature; approval recompute → may freeze (I5). |
| GET | `seals/{seal}/` · `seals/{seal}/verify/` | viewer | D4/E4-base | `verify` re-validates the signature against the canonical payload. |
| POST | `seals/{seal}/revoke/` | seal's reviewer | D4 | Only pre-approval (DP-08); append-only event. |
| GET | `versions/{ver}/seal_plan/` | coordinator | D5 | Seal×section matrix with decisions/proposals + evidence. |
| POST | `versions/{ver}/seal_plan/confirm/` | coordinator | D5 | `{decisions:[{record_id, decision}]}`; single `pending → final` transition (I4); recompute + notify. |

### Observations

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| GET/POST | `versions/{ver}/observations/?status=&cursor=` | viewer / reviewer | D3 | GET: resúmenes paginados. POST: `{section_key, page, quads, snippet, body}`. |
| GET | `observations/{obs}/?version={uuid}` | viewer | D3 | Resumen y metadatos del ancla de la versión solicitada. |
| GET/POST | `observations/{obs}/replies/?cursor=` | viewer / reviewer+editor | D3 | GET: respuestas paginadas. POST: resumen de respuesta y estado actualizado. |
| GET | `observations/{obs}/anchors/?cursor=` | viewer | D3 | Historial paginado de metadatos, sin coordenadas completas. |
| GET | `observations/{obs}/content/?offset=` | viewer | D3 | Texto íntegro por partes. |
| GET | `observations/{obs}/replies/{reply}/content/?offset=` | viewer | D3 | Texto íntegro de una respuesta por partes. |
| GET | `observations/{obs}/anchors/{version_number}/content/?offset=` | viewer | D3 | JSON de coordenadas por partes; el número es de versión, nunca un PK. |
| POST | `observations/{obs}/status/` | author / editor | D3 | State machine (I14). |

#### Lectura progresiva de observaciones (2026-10-02)

Las colecciones devuelven `{results, next_cursor}` con páginas fijas de 25 y
cursor firmado ligado al alcance y filtro. Hilos y respuestas usan orden
estable por fecha/clave descendente; el historial usa número de versión
descendente. El filtro admite `active`, `open`, `answered`, `resolved` y `all`
(default API: `all`; UI: `active`). Los resúmenes conservan identidad, estado,
autor, fechas y versiones, y reemplazan texto completo e historia anidada por
`body_preview` (500 caracteres), `body_length`, `body_content_url`, conteo de
respuestas y metadatos del ancla actual. Las anclas incluyen `version_public_id`
y `version_is_trashed`; la UI conserva la lectura histórica sin enlazar al
visor de una versión en papelera. Las mutaciones devuelven resúmenes,
sin cargar historias completas.

Cada lectura de contenido devuelve `{content, offset, next_offset, eof}` con
hasta 8192 caracteres Unicode, proyectados en SQL. Offset es base cero y no
puede exceder la longitud; filtros, cursores y offsets inválidos producen 400.
El cliente concatena el JSON de coordenadas y lo interpreta sólo al llegar a
EOF. Todo el contenido anterior sigue accesible; no se impone una longitud
nueva a los textos existentes. Todas las rutas mantienen el aislamiento por
proyecto/tenant (404 para quien no es miembro).

### Jobs, notifications, billing, platform

| M | Route | Permission | Flow | Notes |
|---|---|---|---|---|
| GET | `jobs/{job}/` | viewer of the underlying object | C1/C2/E1/A1 | Polling: `{status, progress?, error?, result_ref}`. |
| GET | `me/notifications/` · POST `me/notifications/{id}/read/` | authenticated | D1/D5 | |
| POST | `orgs/{org}/sample-project/` | org admin | A1 | Idempotent re-seed of the sample project ⚙︎ (also used by onboarding retry). |
| GET | `plans/` | — | F1 | |
| GET | `orgs/{org}/subscription/` | org admin | F1 | Plan, limits, usage. |
| POST | `orgs/{org}/subscription/checkout/` | org owner | F1 | Returns gateway checkout URL/preference (DP-01). |
| POST | `billing/webhook/{gateway}/` | — + gateway signature | F1 | CSRF-exempt, signature-verified, idempotent by event id; raw PaymentEvent. |
| GET | `orgs/{org}/invoices/` · `invoices/{id}/download/` | org admin | F1 | Download via signed URL. |
| GET | `orgs/{org}/audit_events/` | org admin | F3-base | Filter by type/project/date. |
| GET | `seal_keys/{key_id}/` | — | E4-base | Ed25519 public key for external verification. |
| GET | `health/` · `staging-banner/` | — | — | Template endpoints, kept. |

## 4. The engine as a queue-consumed service (domain view)

Full input/output contract, pipeline, queues and edge cases live in `05-motor-comparacion.md`.
What the domain sees:

- The domain **only** enqueues an `EngineJob` (payload JSONB) and consumes its `result` — the
  `engine` app imports nothing from `reviews`/`billing`, so it can be extracted to a separate
  deployable without touching domain code.
- Job states: `pending → running → done | failed`, mirrored in
  `DocumentVersion.analysis_status`; idempotent by `idempotency_key` (I15); retries with
  backoff (parse errors are permanent, no retry).
- Job chain per upload: `analysis → comparison(auto, vs previous ready) → seal_review(D5) →
  notify`, serialized per document via a Redis lock (edge case F4 in `05`).
- Celery topology: broker Redis; queues `engine_heavy` (analysis/OCR, low concurrency,
  priority to a new org's first version for A1 < 5 min), `engine_light` (comparisons),
  `default` (domain-transactional work: D5 seal review, notifications, re-anchor).
  `django-celery-beat` inherits the template's operational periodic tasks.

## 5. Roles and permissions

Org roles: `owner` (propietario), `admin`, `member`. Project roles: `admin`, `editor`,
`reviewer` (revisor), `viewer` (lector).

**Effective-role resolution**: org owner/admin ⇒ implicit `admin` on every project of the org;
org member ⇒ whatever their ProjectMembership says; no membership ⇒ no access, expressed as
**404** (not 403) to avoid leaking existence (I12).

| Capability | Owner (org) | Admin (org/proj) | Editor (proj) | Reviewer (proj) | Viewer (proj) |
|---|---|---|---|---|---|
| View projects/documents/history/comparisons | ✓ | ✓ | ✓ | ✓ | ✓ |
| Download version (signed URL, audited) | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create project (org scope) | ✓ | ✓ | ✓ (as org member) | — | — |
| Create document / upload version (C1/C2) | ✓ | ✓ | ✓ | — | — |
| Request review (D1) | ✓ | ✓ | ✓ | — | — |
| Create/reply observations (D3) | ✓ | ✓ | ✓ | ✓ | — |
| Seal (D4) | ✓* | ✓* | — | ✓ | — |
| Confirm D5 seal plan (coordinator) | ✓ | ✓ | — | only if designated | — |
| Configure project: checklist/owners/rules (B3) | ✓ | ✓ | — | — | — |
| Invite / manage members (A2) | ✓ | ✓ (org, or own project) | — | — | — |
| Billing: plan, payment, invoices (F1) | ✓ | view | — | — | — |
| View org audit events | ✓ | ✓ | — | — | — |

\* Admin/owner may seal (implicit reviewers), but the seal's `signed_payload` always records
the actual role and assignment — probative weight is preserved. Editors do NOT seal
(soft author/reviewer separation; engine edge case F7 in `05`).

**Coordinator (D5/E4)** is NOT a sixth role: it is the capability `can_confirm_seal_plan` =
project admins by default + users designated in `ProjectConfigVersion.coordinators` (may
include reviewers) — DP-07.

**Implementation**: in `core/permissions.py`, FBV-compatible decorators —
`@require_project_role('editor')`, `@require_org_role('admin')`,
`@require_seal_plan_confirmer` — resolve the object from URL kwargs (project/document/version →
walk up to the project), compute `resolve_effective_role(user, project)` once per request
(cached on `request`), attach `request.project`/`request.org`, and answer 404 on
non-membership. Services receive the actor and re-validate invariants (defense in depth).

## 6. Notifications & email

- MVP channel: **email** + a minimal in-app inbox (`me/notifications/`).
- New `EmailTemplateRegistry` in `notifications` replaces the template's f-string emails:
  every email type declared once (subject/body templates, variables), rendered with Django
  templates; auth emails (reset code) migrate onto it.
- D5 delivery rule (S6): one grouped email per affected reviewer, zero email to preserved
  reviewers; review-cycle notifications are transactional and never rate-limited away.

## 7. Open questions (DECISIÓN PENDIENTE)

| ID | Question | Recommendation |
|---|---|---|
| DP-01 | Payment gateway for LATAM (F1). | **RESOLVED (operator, 2026-07-12): Wompi** (Colombia-first), behind a `PaymentGateway` adapter so the gateway stays swappable; checkout via Wompi's hosted widget, webhook verified with Wompi's event signature. |
| DP-06 | Upload: presigned PUT vs multipart to the API. | **Presigned PUT** + authoritative `complete/` (hash, parse, limits); `UPLOAD_DIRECT_FALLBACK` flag for test environments. |
| DP-07 | Coordinator: new role vs capability. | **Capability** `can_confirm_seal_plan` (project admins + designated users). Avoids a sixth role and a matrix rewrite. |
| DP-08 | Withdraw my seal. | Allowed pre-approval only, as append-only event (see `02`). |
