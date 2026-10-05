---
trigger: manual
description: Error documentation and known issues tracking. Reference when debugging, fixing bugs, or encountering recurring issues.
---

# Error Documentation — Versiona

This file tracks known errors, their context, and resolutions. When a reusable fix or correction is found during development, document it here to avoid repeating the same mistake.

---

## Format

```
### [ERROR-NNN] Short description
- **Date**: YYYY-MM-DD
- **Context**: Where/when this error occurs
- **Root Cause**: Why it happens
- **Resolution**: How to fix it
- **Files Affected**: List of files
```

---

## Known Issues

### [ERROR-005] UploadThrottle is inert (open, by design until redesigned)
- **Date**: 2026-07-22
- **Context**: `documents/views.py` upload endpoints appear rate-limited (20/hour) but are not.
- **Root Cause**: `ScopedRateThrottle` reads `view.throttle_scope`, which `@api_view` FBVs never set — `allow_request` returns True silently.
- **Resolution**: pending a deliberate design: switching to a `SimpleRateThrottle` subclass would immediately rate-limit the CI E2E suite (same IP, many uploads). Needs a higher rate + cache strategy first. Public endpoints already use the correct subclasses.
- **Files Affected**: `backend/documents/views.py:24`

---

## Resolved Issues

### [ERROR-001] Bare colon in a workflow step name killed the whole CI file
- **Date**: 2026-07-22
- **Context**: Push after adding the OCR apt step — GitHub reported "This run likely failed because of a workflow file issue"; zero jobs started.
- **Root Cause**: `name: Install OCR system deps (ocrmypdf: tesseract...)` — the unquoted `:` inside the step name is a YAML mapping separator.
- **Resolution**: reworded the name without a colon; validate locally with `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` before pushing workflow edits.
- **Files Affected**: `.github/workflows/ci.yml`

### [ERROR-002] Backend OCR suites red only in CI (ocrmypdf subprocess error)
- **Date**: 2026-07-22
- **Context**: 3 scanned-PDF tests (engine pipeline ×2, reviews hardening ×1) failed in CI, passed on the VPS.
- **Root Cause**: runners lacked the system binaries ocrmypdf shells out to (`tesseract`, `tesseract-spa` data, `ghostscript`); the VPS has them installed.
- **Resolution**: apt step in the backend-tests job only (E2E uses text-native fixtures and never triggers OCR). unpaper/pngquant/qpdf NOT needed for `optimize=0` + bundled libqpdf.
- **Files Affected**: `.github/workflows/ci.yml`, `backend/engine/services/ocr.py`

### [ERROR-003] Four E2E email flows died in CI on ECONNREFUSED :8025
- **Date**: 2026-07-22
- **Context**: a2-invite-team, d1-request-review, d5-selective-invalidation and the master journey — 100% failing in CI, green locally.
- **Root Cause**: no mailpit service container and no `DJANGO_EMAIL_*` env in the e2e job → Django fell back to console email and `e2e/helpers/mailpit.ts` fetches crashed.
- **Resolution**: `axllent/mailpit` service (ports 1025/8025, `/livez` healthcheck) + SMTP env block in the frontend-e2e-tests job.
- **Files Affected**: `.github/workflows/ci.yml`, `frontend/e2e/helpers/mailpit.ts`

### [ERROR-004] Quality gate reported ~26 phantom errors (parser bugs, not test bugs)
- **Date**: 2026-07-22
- **Context**: test-quality-gate red with "empty body"/"unnamed test"/duplicate-title errors across ~20 spec files.
- **Root Cause**: the jest AST parser classified `test.use/slow/setTimeout` as test declarations and rendered template-literal titles as empty; the backend analyzer didn't count `pytest.raises` as an assertion.
- **Resolution**: fixed the analyzers (NON_TEST_MEMBERS set; quasi-join titles with a `${…}` placeholder; `"raises"` in ASSERTION_PATTERNS). Audit the gate before mutating tests when it disagrees with reality.
- **Files Affected**: `frontend/scripts/ast-parser.cjs`, `scripts/quality/backend_analyzer.py`

### [ERROR-006] b3 spec raced the checklist render (deterministic CI failure)
- **Date**: 2026-07-22
- **Context**: `b3-e3-governance.spec.ts` failed 1/2 in CI (fresh seed), passed locally (persistent DB carried old checks).
- **Root Cause**: `count() - 1` read immediately after clicking `add-check` — React hadn't committed the new row, so index resolved to -1.
- **Resolution**: capture `initialCount` before the click, then `await expect(rows).toHaveCount(initialCount + 1)` and use `initialCount` as the index.
- **Files Affected**: `frontend/e2e/app/projects/b3-e3-governance.spec.ts`

### [ERROR-007] MySQL migration: four failures the engine swap surfaced
- **Date**: 2026-08-03
- **Context**: moving the project from PostgreSQL 16 + pgvector to MySQL 8.0 to align with
  the MySQL-first fleet tooling (`migrate-project`, `full-audit`, `setup-mysql.sh`).
- **Root Causes and Resolutions** (each was a green-but-wrong failure mode):
  1. Django SKIPS `UniqueConstraint(condition=...)` on MySQL without erroring, so five
     invariants — including I4 — would have vanished with `migrate` reporting success.
     Replaced with `GeneratedField(db_persist=True)` + plain `UniqueConstraint`, and
     covered by 13 new tests that did not exist before.
  2. `CREATE TRIGGER` failed with error 1419 (binary logging on, no SUPER). Granted the
     dynamic privilege `SET_USER_ID` rather than `SUPER`.
  3. `TransactionManagementError` on the trigger migration: MySQL cannot roll back DDL, so
     `documents/0002` and `0004` need `atomic = False`.
  4. InnoDB updates FULLTEXT indexes at COMMIT, so the B2 search tests found nothing
     inside the usual rollback-only test transaction — and the negative test passed
     vacuously. They now run with `transaction=True`, which in turn tripped the I2 trigger
     during the flush (`DELETE FROM`, where PostgreSQL used `TRUNCATE CASCADE`); an
     autouse fixture trashes versions before teardown.
- **Files Affected**: `versiona_project/db.py`, `documents/search.py`,
  `documents/migrations/0002`–`0005`, `core/migrations/0001_extensions.py`, the five
  models carrying generated columns, `conftest.py`, `.github/workflows/ci.yml`.

---

## Database provisioning (MySQL 8, native — nothing in the repo did this before)

Run once per host, as a MySQL admin (`sudo mysql --defaults-file=/etc/mysql/debian.cnf`):

```sql
CREATE DATABASE `versiona_project_db` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
-- Throwaway database for the Playwright suite (backend/.env.e2e).
CREATE DATABASE `versiona_e2e`        CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- validate_password is MEDIUM here: >= 8 chars with upper, lower, digit and symbol.
CREATE USER 'versiona_project_user'@'localhost' IDENTIFIED BY '<password>';
GRANT ALL PRIVILEGES ON `versiona_project_db`.* TO 'versiona_project_user'@'localhost';
GRANT ALL PRIVILEGES ON `versiona_e2e`.*        TO 'versiona_project_user'@'localhost';
-- pytest-django creates and drops test_<name>; the pattern grant covers both databases.
GRANT ALL PRIVILEGES ON `test\_versiona%`.*     TO 'versiona_project_user'@'localhost';
-- Required to CREATE TRIGGER while binary logging is on (error 1419 otherwise).
-- Narrower than SUPER; TRIGGER itself comes with GRANT ALL on the schema.
GRANT SET_USER_ID ON *.* TO 'versiona_project_user'@'localhost';
FLUSH PRIVILEGES;
```

Verification after `migrate`:

```sql
SHOW TRIGGERS FROM versiona_project_db;                      -- exactly 2
SELECT DISTINCT INDEX_NAME FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA='versiona_project_db' AND NON_UNIQUE=0
    AND INDEX_NAME LIKE 'uniq_%';                            -- the 5 invariants present
SELECT TABLE_NAME, COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA='versiona_project_db'
    AND COLLATION_NAME NOT IN ('utf8mb4_0900_ai_ci');        -- the identity columns only
```

`slug` and `slug_alive` must NOT appear in that last query: if their collations diverge,
the unique index compares by different rules than the application does.

## Resuelto 2026-10-03 — fragmentos de quads grandes agotaban el sort de MySQL

La prueba con coordenadas históricas superiores a 256 KB devolvió MySQL 1038 al
leer un fragmento. `first()` agregaba orden por PK a una consulta proyectada;
MySQL ordenaba la fuente JSON grande antes de devolver la parte solicitada.
`observations.queries.content_fragment` elimina el orden y limita con un slice
la fila que cada ruta ya identifica de forma única. La reconstrucción Unicode
de ese JSON pasó en MySQL después de corregir la consulta.
