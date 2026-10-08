# Technical — Versiona

> Memory Bank core file. Infra detail: `docs/plan/07-infraestructura.md`; security:
> `docs/plan/08-seguridad.md`.

## Stack (verified versions)

| Layer | Tech |
|---|---|
| Backend | Python 3.12 · Django 6.0.5 · DRF 3.17 · simplejwt 5.5 (+token_blacklist) |
| Async | Celery 5.6 (Redis broker/results; queues default/engine_light/engine_heavy; static `CELERY_BEAT_SCHEDULE`; eager in dev/tests) |
| Data | MySQL 8.0 (utf8mb4 / utf8mb4_0900_ai_ci; identity columns pinned to utf8mb4_bin). Partial unique indexes are emulated with STORED generated columns; I2/I2a live in two triggers |
| Files | MinIO (native systemd, bucket `versiona-media`) via django-storages S3; FileSystem fallback when no bucket configured |
| PDF engine | PyMuPDF 1.28 (+ reportlab for fixtures); OCR mandatory since It5: ocrmypdf 17.8 + tesseract-spa with confidence gating (DP-02); `analyze_bytes(allow_ocr=)` for the anonymous comparator |
| Frontend | Next.js 16.2 (App Router) · React 19.2 · TS strict · Tailwind v4 (OKLCH tokens) · Zustand 5 · axios `api` (401 refresh single-flight) + bare `publicApi` for AllowAny endpoints |
| Billing (It9) | `billing.Subscription` (14-day Pro trial on signup) + static `PLANS` catalog; `effective_plan` = console override > active trial > free (lazy) |
| Public surface (It9) | `public_tools` app: anonymous comparator (`/api/public/comparisons/`, ephemeral MinIO files, 24h TTL, per-IP SimpleRateThrottles) + `GET /api/public/plans/` |
| Testing | pytest(+django/cov/factory-boy/freezegun) — 484 tests · Jest 30 + RTL — 271 tests · Playwright 1.60 + flow-coverage reporter — 53 tests / 27 specs / 36 flows |
| Email dev | mailpit (SMTP :1025, REST API :8025 — E2E asserts selective D5 emails against it; CI runs an `axllent/mailpit` service container) |

## Dev environment (native — no Docker, DP-21)

- System services on this VPS: `mysql`, `redis-server`, `minio.service`,
  `mailpit.service` (units in /etc/systemd/system; MinIO env in /etc/default/minio).
- Backend: `backend/venv`; `.env` holds DB/MinIO/mailpit config (gitignored).
- Commands: `venv/bin/python manage.py runserver` · `venv/bin/celery -A versiona_project
  worker|beat` · `npm run dev` · fixtures: `venv/bin/python testdata/generate_pdfs.py`.
- CI: GitHub Actions with mysql+redis+minio+mailpit services; OCR system deps
  (tesseract/tesseract-spa/ghostscript) in the backend job; `makemigrations --check`
  anti-drift; Playwright browser cache; separate Test Quality Gate workflow.

## Key constraints & decisions

- El harness Playwright admite `E2E_PYTHON_BIN` absoluto para reutilizar un venv
  externo sin enlazar `backend/venv`. El entorno de sus procesos omite valores
  `undefined`; se mantiene el Python local como default. En worktrees, las
  pruebas usan nombres de DB descartables explícitos y puertos UI/API propios.

- Docker/compose deferred (DP-21) — kept as blueprint in `docs/plan/07` §2.2.
- Payment gateway: **Wompi** behind a `PaymentGateway` adapter (DP-01, It7).
- `d5_mode` default **auto** (DP-03); free-plan retention locks access, never deletes (DP-04).
- Search: MySQL FULLTEXT over `SectionVersion.search_text`, which holds accent-folded,
  Snowball-stemmed Spanish tokens built in Python (`documents/search.py`). InnoDB updates
  a FULLTEXT index at COMMIT, so tests that assert a match must run transactionally.
- Coverage gates (as enforced today): pytest `--cov-fail-under=80` (backend total ~92%)
  + engine module gate 95% in CI (`scripts/ci/coverage-module-gate.py`); Jest
  `coverageThreshold` = global-residual 50 lines · `lib/stores/` 75 · gated component
  dirs (compare/seals/versions/reviews/observations/checks/certificates) 80.
- Test Quality Gate: `scripts/test_quality_gate.py --external-lint run
  --semantic-rules strict` (errors block; ruff via backend venv; AST parser for jest).
- Trial: `BILLING_TRIAL_DAYS=14`; anonymous comparator caps: 10MB/file, 100 pages,
  TTL 24h (`PUBLIC_COMPARE_*` settings, env-overridable).
