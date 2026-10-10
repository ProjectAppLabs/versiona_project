# 08 — Security

> Role-based authorization on every endpoint and every screen, integrity (version hash, seal
> signature), the audit log recorded from the MVP on, and safe handling of uploaded files.
> Invariants referenced from `02-modelo-datos.md` (I…); endpoint permissions detailed in
> `03-backend.md` §3 and §5.

## 1. Base reused

- Template auth hardening kept: simplejwt short-lived access (15 min) + rotating refresh,
  reCAPTCHA on public auth endpoints, production security headers in `settings_prod.py`
  (HSTS 1y + subdomains + preload, SSL redirect, secure cookies, nosniff, `X_FRAME_OPTIONS=
  DENY`, proxy SSL header), CORS/CSRF allow-lists via env.
- Fix inherited gap: `rest_framework_simplejwt.token_blacklist` must be added to
  `INSTALLED_APPS` (the template sets `BLACKLIST_AFTER_ROTATION=True` without the app, so the
  blacklist is inert).
- The base CLAUDE.md security checklist (no secrets in code, `.env` gitignored, validated
  input server+client, no raw SQL, serializers never `__all__` on sensitive models, DEBUG off,
  ALLOWED_HOSTS set, `pip audit`/`npm audit` clean) applies to every iteration's DoD.

## 2. Authorization

### Vinculación de identidad y revocación de sesiones (2026-10-10)

- Google se identifica por el `sub` de claims verificados. Coincidir en correo
  no permite vincular ni iniciar sesión en una cuenta existente sin vínculo.
- Todas las cuentas históricas sin `sub` pasan por recuperación por correo;
  no se presupone que una contraseña utilizable pruebe la titularidad.
- El vínculo exige una sesión vigente, ticket de esa recuperación, contraseña
  actual, contraseña nueva distinta y segundo factor cuando corresponda.
  La comprobación local y la escritura se serializan sobre el usuario. Un
  `sub` ya asignado no puede transferirse ni sustituirse.
- Recuperar o cambiar la contraseña y completar el vínculo incrementa
  `auth_version`. Access, refresh y desafíos TOTP anteriores se rechazan de
  inmediato; los tokens antiguos sin claim sólo se admiten en versión cero.
- El ticket de recuperación dura 15 minutos, está ligado a su propósito,
  usuario y versión, y no es una credencial de sesión. El frontend lo guarda
  temporalmente en `sessionStorage`, nunca en la URL.
- TOTP existente se conserva. Si un tercero instaló un segundo factor antes
  de recuperar la cuenta, su recuperación asistida sigue fuera del alcance
  de esta ronda; no se desactiva TOTP automáticamente.

### 2.1 Per endpoint

The full endpoint × minimum-role table lives in `03-backend.md` §3; the model:

- FBV decorators from `core/permissions.py` — `@require_project_role('viewer'|'editor'|...)`,
  `@require_org_role('member'|'admin'|'owner')`, `@require_seal_plan_confirmer` — resolve the
  object from URL kwargs, compute the **effective role** (org owner/admin ⇒ implicit project
  admin; else the ProjectMembership; else nothing) once per request, and answer **404** on
  non-membership (existence is never leaked across tenants — I12).
- Every queryset goes through `scoped_queryset(user, org/project)`; a bare
  `Model.objects.filter` on tenant data is a review-blocking offense, and the API integration
  matrix (`06` §4) asserts 401/403/404 per endpoint per role.
- Services re-validate the actor against invariants (defense in depth: the permission layer
  can be bypassed by a future internal caller; invariants cannot).
- Throttling scopes: auth endpoints 5/min, `upload_intent` 20/h per user, billing webhook by
  IP+signature; global default rate for authenticated traffic.

### 2.2 Per screen (frontend)

The `proxy.ts` guard keeps unauthenticated users out of the `(app)` group; role gating inside
screens follows the same matrix (`04` §2 access column):

| Screen / control | viewer | reviewer | editor | admin/owner |
|---|---|---|---|---|
| Board, project view, timeline, viewer, compare | ✓ | ✓ | ✓ | ✓ |
| UploadDropzone, "request review" | — | — | ✓ | ✓ |
| Observation composer / replies | — | ✓ | ✓ | ✓ |
| Seal button (SealActionBar) | — | ✓ (assigned) | — | ✓ (implicit reviewer) |
| InvalidationReviewCard (confirm D5 plan) | — | only if designated coordinator | — | ✓ |
| Project settings (B3/E3), members | — | — | — | ✓ |
| Org billing (F1) | — | — | — | owner (admins view) |

UI gating is UX, not security: the API enforces every rule regardless of what the client
renders.

## 3. Integrity

### 3.1 Version hash (I9)

- sha256 computed **server-side** at `complete/` by streaming the object from MinIO (the S3
  multipart ETag is not a content hash), persisted on `DocumentVersion.sha256` and as S3
  metadata `x-amz-meta-sha256`.
- Re-verified: before signing any seal, and when issuing a download URL. Mismatch ⇒ version
  quarantined + `AuditEvent` + ops alert.

### 3.2 Seal signature (I6) — Ed25519

HMAC was considered and discarded: verification would require sharing the secret, so it proves
nothing to a third party and is repudiable. Ed25519 gives offline public verification — the
requirement behind the future exportable certificate (E4) — with 64-byte signatures and native
support in `cryptography`.

- **Canonical payload** (UTF-8 JSON, sorted keys, no whitespace):
  `{"v":1, "seal_id":…, "org":…, "project":…, "document":…, "version_number":N,
  "version_sha256":…, "reviewer":{"id":…, "email":…, "role":…}, "covers_all":bool,
  "sections":[{"stable_key":…, "body_hash":…} … sorted by key], "config_version":n,
  "signed_at":"ISO8601Z"}`
- `signature = Ed25519.sign(private_key, payload_bytes)`; persisted: `signed_payload`,
  `signature` (base64), `key_id`.
- **Key management**: private key as PEM file mode 0400 outside the repo, path via
  `SEAL_SIGNING_KEY_PATH`; production ideally a secret manager/KMS (DP-24). Rotation by
  `key_id` — old signatures keep verifying against their historical public key. Public keys
  exposed at `GET /api/seal_keys/{key_id}/`.
- **Third-party verification** (E4 groundwork): hand over payload + signature + public key;
  the verifier needs no system access, and `version_sha256` binds the signature to the exact
  binary.

## 4. Audit log (from the MVP)

`audit.record()` is called inside the same transaction as the mutation. Envelope on every
event: `{actor_id?, org_id, project_id?, object_type, object_id, request_id, ip, ts}` —
append-only, denormalized ids, no cascades (survives any deletion). F3 (full UI + export) is
V2; the data exists from day one.

| Event | Specific payload |
|---|---|
| `auth.sign_in` / `auth.sign_in_failed` / `auth.impersonation_started` | method (password/google); target user on impersonation |
| `org.created` / `org.member_added` / `org.member_role_changed` / `org.member_removed` | roles before/after |
| `invitation.sent` / `invitation.accepted` / `invitation.revoked` | email, role, project? |
| `project.created` / `project.updated` / `project.config_changed` | config_version from→to + rule diff |
| `document.created` / `version.uploaded` / `version.analysis_failed` | number, sha256, size, scenario / error |
| `version.downloaded` | version_number, TTL issued |
| `comparison.created` | from, to, trigger |
| `review.requested` | assignees + scopes |
| `seal.created` | seal_id, sections, covers_all, key_id |
| `seal.preserved` / `seal.invalidated` / `seal.revoked_by_reviewer` | to_version, reason_code, decided_mode, decided_by?, evidence summary |
| `seal_plan.confirmed` | decided records + overrides |
| `observation.created` / `observation.status_changed` / `observation.replied` | section, transition |
| `version.approved` / `approved_pointer.moved` | supporting seals / from→to |
| `subscription.created` / `subscription.updated` / `payment_failed` / `billing.webhook_received` | plan, status, gateway_event_id |

MVP records **all writes** plus downloads; pure reads (page views) join in V2 with F3.

## 5. Safe file handling (uploads & downloads)

1. **Type validation by content, not extension**: magic bytes `%PDF-` + a full PyMuPDF parse
   before accepting (rejects corrupted/mislabeled files) — asserted with the `corrupto.pdf`
   fixture.
2. **Encrypted/protected PDFs rejected** (`doc.needs_pass`) with an actionable message —
   `protegido.pdf` fixture.
3. **Size/page limits** (DP-11): proposed 100 MB / 500 pages paid, 25 MB free — enforced in
   the presigned policy (`content-length-range`) and re-verified at `complete/`; values live
   in `Plan.limits` (I13).
4. **Server-generated object keys** (`02` §6): the user's filename never touches bucket or
   filesystem; the original name is stored sanitized (no path separators/control chars,
   ≤ 255) as display metadata only.
5. **Content-type pinned** to `application/pdf` on upload; downloads served with
   `response-content-disposition: attachment` (never rendered inline from the API domain).
6. **Plan limits at intent time** (I13) and upload throttling (20/h).
7. **Antivirus**: deferred (DP-12) — strict parsing + fixed content-type + attachment
   disposition mitigate; ClamAV joins as an async AnalysisJob step before GA or if public
   sharing ships.
8. **Bucket posture**: private bucket, SSE on, versioning ON, Object Lock (governance) in
   production for sealed versions (object-layer backup of I2/I4); access exclusively through
   signed URLs — download TTL 5 min, upload TTL 15 min.

## 6. Open questions (DECISIÓN PENDIENTE)

| ID | Question | Recommendation |
|---|---|---|
| DP-24 | Production home for the Ed25519 private key: PEM on disk vs secret manager/KMS. | PEM 0400 acceptable for staging; adopt a secret manager before the first paying regulated customer. |
| DP-11 | Final size/page limits per plan. | 100 MB / 500 pages paid, 25 MB free (in `Plan.limits`). |
| DP-12 | ClamAV in the MVP pipeline. | Defer; add as async step pre-GA. |
