---
trigger: manual
description: Project intelligence and lessons learned. Reference for project-specific patterns, preferences, and key insights discovered during development.
---

# Lessons Learned — Versiona

This file captures important patterns, preferences, and project intelligence that help work
more effectively with this codebase. Updated as new insights are discovered. The canonical
copy of the architecture/style lessons lives in `CLAUDE.md` (project-specific section);
this file records the *discovered-the-hard-way* items.

---

## 1. Iteration 0 findings (2026-07-12)

### MySQL drops conditional unique constraints SILENTLY (2026-08-03)
- `UniqueConstraint(condition=...)` has no MySQL equivalent
  (`supports_partial_indexes = False`). Django does not fail — it emits a
  `models.W039` warning, skips the constraint and lets `migrate` finish green. Five
  product invariants, including I4 (one active seal per reviewer), would have been
  unenforced with a passing test suite, because **no test asserted any of them**.
- Fix: the condition moves into a `GeneratedField(db_persist=True)` that is NULL when the
  row does not qualify; a plain `UniqueConstraint` over that column reproduces the rule,
  because a UNIQUE index ignores NULLs. `STORED` is mandatory (PostgreSQL has no VIRTUAL).
- The real lesson is not about MySQL: a DB-level invariant with no test is a
  configuration detail, not a guarantee. The canary is
  `manage.py check --database default | grep "unique constraints with conditions"` → must
  be 0, and `reviews/tests/test_partial_unique_invariants.py` is what actually holds I4.

### Three MySQL behaviours that only surface at runtime (2026-08-03)
- **DDL cannot run inside an atomic migration** (`can_rollback_ddl = False`). Any
  migration creating a trigger or a FULLTEXT index needs `atomic = False`.
- **Creating a trigger needs more than the TRIGGER privilege** when binary logging is on:
  error 1419. Granting the dynamic privilege `SET_USER_ID` is enough and far narrower
  than `SUPER`.
- **The transactional-test teardown fights the I2 trigger.** Django's
  `TransactionTestCase` flush always issues `DELETE FROM` (its `reset_sequences` is
  hardcoded False), and the trigger correctly rejects deleting a version that never went
  through the trash. PostgreSQL never showed this because its flush uses
  `TRUNCATE CASCADE`, which does not fire row triggers. Handled by an autouse fixture in
  `conftest.py` that trashes versions before the flush — satisfying the invariant instead
  of bypassing it.

### Celery replaces Huey with less surface than planned
- Static `settings.CELERY_BEAT_SCHEDULE` + Redis result backend cover everything the
  template's Huey setup did — the django-celery-beat/results apps were skipped on purpose
  (fewer Django 6 compatibility risks). Huey's `task.call_local()` in tests becomes a plain
  function call.

### Deterministic PDFs need two switches
- reportlab: `canvas.Canvas(..., invariant=1)` fixes dates/producer.
- PyMuPDF: `doc.save(..., no_new_id=True)` — without it every save mints a random /ID and
  byte-reproducibility breaks (caught by double-run sha256 comparison).

### The template's CLAUDE.md described a different project
- Its "content app / EmailTemplateRegistry / MySQL 8" section did not match the actual code
  (`base_feature_app`, plain f-string emails). Trust exploration over inherited docs; the
  identity section is now Versiona's real state.

### git mv + Edit tool interplay
- After `git mv`, files must be re-read at the new path before editing; global seds run
  after a read also invalidate it. Sequence renames → seds → reads → edits to avoid churn.

## 2. It1–It9 findings (2026-07-22)

### Plan state has ONE reading path
- `Organization.plan` (console override, always wins) + `billing.Subscription` (trial)
  resolve ONLY through `billing.services.effective_plan`/`usage_report` — lazy at read
  time, so correctness never depends on the beat task having run. Never read `org.plan`
  directly for limits.

### ScopedRateThrottle is a silent no-op on FBVs
- DRF's `ScopedRateThrottle` reads `view.throttle_scope`, which `@api_view` never sets —
  the throttle allows everything without erroring (`documents/views.py` UploadThrottle
  shipped inert). Use `SimpleRateThrottle`/`AnonRateThrottle` subclasses with a class
  `scope`. Throttle counters live in locmem → per-process; Redis cache is the follow-up
  before real traffic.

### The engine's pure core is the reuse surface
- `analyze_bytes(bytes) -> dict` and `compare_snapshots(a, b) -> dict` are pure and
  model-free — the anonymous comparator reuses them without touching DocumentVersion or
  any D5 path. Additive flags with safe defaults (`allow_ocr=True`) keep authed paths
  byte-identical.

### Celery eager mode is the CI/dev degradation strategy
- `CELERY_TASK_ALWAYS_EAGER` (non-production default) makes async endpoints complete
  inline — the public comparator needs no worker in CI/E2E, and POST latency in dev is
  the full processing time (acceptable; prod returns 202 fast).

### Specs anchor to testids, never to copy
- Every It9 copy change broke exactly the tests that asserted literal strings
  ('Wompi', 'Crear cuenta gratis', '/dashboard'). data-testid contracts + accessible
  roles survive copy/i18n changes; `getByText` on marketing copy does not.

### CI failures come in environment flavors
- Three distinct root-cause families in one red PR: missing system binaries
  (tesseract/ghostscript), missing service container (mailpit → ECONNREFUSED), and a
  YAML footgun (a bare `:` inside a step name kills the whole workflow file). Check
  `gh run view` for "workflow file issue" BEFORE debugging tests.

### The quality gate's parsers are code too
- ~26 of its "errors" were parser bugs (test.use/slow classified as tests; template
  literal titles rendered empty; pytest.raises not counted as assertion). When a gate
  disagrees with reality, audit the gate before mutating the tests.

### Playwright determinism patterns that stuck
- Never `count()-1` right after a click (b3 race) — capture `initialCount` then
  `toHaveCount(initialCount+1)`. Never `networkidle` — wait a stable, unconditional
  locator per screen. Modal backdrops can't be clicked at center (the dialog covers
  it) — use the accessible close button.

## 3. Product guardrails (never relearn these)

- D5 conservative bias (I7): no code path may preserve a seal without exact normalized
  body-hash equality. False-invalidate is acceptable; false-preserve never (S4).
- Versions/seals are append-only (I2–I4); "delete" features (C4/B4) are V2 and still never
  touch sealed history.
- The `testdata/` truth table is a contract: engine/E2E assertions must match it exactly,
  and any change to it requires regenerating fixtures via the script in the same PR.

### Primer factor y desafíos TOTP (2026-10-01)

- Un `202` válido contiene `requires_2fa: true` y un desafío no vacío. Los campos
  de tokens accidentales se ignoran hasta completar el segundo factor; un desafío
  mal formado se rechaza aunque incluya tokens.
- Las pruebas del store observan su estado real y la frontera de persistencia
  mockeada. La ausencia de cookies de sesión se comprueba en el navegador real.
- Para probar un error del formulario TOTP, acotar `role=alert` al paso de código:
  Next también agrega un anunciador de rutas con ese rol.

### Reanudación del análisis (2026-10-01)

- El checkpoint privado y los efectos de una fase se confirman en una transacción
  con lock del job. La forma del resultado público se conserva y sólo se publica
  al terminar.
- Las versiones de fixtures nacen PENDING antes del análisis real. Los triggers
  de inmutabilidad siguen activos en MySQL; una versión READY antigua sin un
  checkpoint comprobable se conserva y el job se detiene.

### Lectura progresiva e I11 (2026-10-03)

- Los offsets de textos y JSON usan caracteres Unicode del servidor. El cliente
  conserva `next_offset`; `string.length` de JavaScript cuenta unidades UTF-16 y
  puede repetir u omitir contenido con emoji. JSON se interpreta sólo al llegar
  a EOF.
- Al proyectar un fragmento de JSON grande desde una fila única, eliminar el
  orden y usar un slice con límite. `QuerySet.first()` vuelve a agregar orden
  por PK cuando el queryset no está ordenado, lo que puede agotar la memoria de
  ordenación de MySQL aun con una salida pequeña.
- I11 recorre versiones vivas reales, no diferencias entre números. Los huecos
  y la papelera no exigen un enlace; un corte no se repara con un preserved
  posterior. La comprobación escalar también exige el mismo documento.
- Los mocks de un 429 deben conservar `detail` y `Retry-After` de DRF. Un payload
  inventado con `error` puede ocultar un fallo de presentación del límite real.
