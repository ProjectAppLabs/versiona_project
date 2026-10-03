# 04 — Frontend

> Route/screen map (React via Next.js App Router, inherited from the base), the component tree
> and state management, and the API contract each screen consumes. The star screen is the
> side-by-side comparison (E1). Endpoints referenced here are defined in `03-backend.md`.

## 1. Base reused

- **Auth, end to end**: `lib/services/http.ts` (axios, `/api` baseURL through the Next rewrite
  to Django, Bearer injection, 401 refresh with single-flight), `lib/services/tokens.ts`
  (cookies), `lib/stores/authStore.ts`, `proxy.ts` route guard (Next 16), `useRequireAuth`,
  pages `/sign-in`, `/sign-up`, `/forgot-password`, `/admin-login` (Django admin SSO handoff),
  Google OAuth + reCAPTCHA. Reused as-is with Versiona copy.
- **State pattern**: Zustand v5 store shape (`fetch + loading/error + selectors`, e.g. the
  template's `productStore`) is the blueprint for every new store; `StagingGate` provides the
  proven polling pattern the generic `jobStore` generalizes.
- **Design system**: Tailwind v4 OKLCH tokens in `app/globals.css` + `next-themes` dark mode +
  accessible `ThemeToggle`. Rebrand = edit tokens, no component changes.
- Removed (demo e-commerce): pages `catalog`, `products/*`, `blogs/*`, `checkout`,
  `backoffice`, home content; stores `cartStore`, `productStore`, `blogStore`; their specs and
  flow definitions. `/manual` is recycled as `/help`. The MVP operational admin is the Django
  admin (no in-app backoffice).

## 2. Route & screen map

Flat routes without an org slug in MVP (active org lives in `orgStore`; DP-15). Protected
route group `app/(app)/` extends the existing `proxy.ts` guard.

| Route | Screen | Flow(s) | Key content & states | Access |
|---|---|---|---|---|
| `/` | Versiona landing (replaces e-commerce home) | A1 entry | Hero + sign-up CTA | Public |
| `/sign-up`, `/sign-in`, `/forgot-password`, `/admin-login` | Auth (template, re-copy) | A1 | submit loading, credential errors, captcha | Guest |
| `/onboarding` | **OnboardingWizard** (4 steps) | A1 | 1) name org → 2) sample-project job progress (retryable) → 3) guided tour over the ready comparison → 4) upload your own PDF. Emits timestamps for the < 5 min metric (S1). Guard: org already set up → `/projects`. | Auth, no org configured |
| `/projects` | Projects board (replaces `/dashboard`, which 308-redirects) | B2 | Cards with StatusBadge (draft / in review / with observations / approved), state filters, name+content search toggle; skeleton grid, empty ("create your first project" → B1), error+retry | Org member |
| `/projects/new` | Create project (30-second form) | B1 | name+description only; inline validation; plan-limit error → upgrade modal (F1) | admin/editor |
| `/projects/[projectId]` | Project view — tabs **Documents / Activity / Team** | B2, C1, A2 | Document list (latest version, traffic light, seals summary); empty state with a large **UploadDropzone** (C1); dedicated 403/404 | Project members |
| `/projects/[projectId]/settings` | Project settings — tabs **Checklist (E3) / Section owners / Approval rules** (incl. `d5_mode`) | B3, E3 | "Changes are never retroactive" notice (I8); dirty-state guard; save states | Project admin |
| `/projects/[projectId]/documents/[docId]` | Document timeline | C3, C2, C1 | **VersionTimeline** (author/date/message/traffic light/approved badge) + UploadDropzone for new versions + pick-two-versions → compare; live job states (polling); per-version download (signed URL); `locked` badge on free-plan old versions (DP-04) | Members |
| `.../versions/[versionId]` | **Version viewer** | D2, D3, D4, D5, E3 | PdfViewer + side panel tabs **Sections / Observations (D3) / Checks (E3) / Seals (D4-D5)**; `?review=<id>` activates the ReviewContextBar (D2); approved versions show a frozen banner + badge | Members; sealing only assigned reviewer; plan confirmation only coordinator |
| `.../compare/[baseId]/[targetId]` | **THE STAR SCREEN — CompareView** | E1, C3, D5 evidence | Three views via `?view=side\|sections\|summary` (side-by-side default); "comparing…" job state when not cached; view switches preserve the active section; deep links `#sec-<key>`; explicit "no changes" state | Members (incl. viewer) |
| `.../reviews/[reviewId]` | Review request detail | D1, D2 | Per-reviewer status, pending sections, "review now" CTA → viewer with `?review=` | Members; actions per assignment |
| `/inbox` | Reviewer inbox | D1, D2, D5 | Pending reviews + re-reviews from invalidation + coordinator confirmations, grouped by project, oldest first; header badge counter; empty "you're all caught up" | Auth |
| `/org/settings` | Org settings — tabs **General / Members (A2) / Plan & billing (F1)** | A2, F1 | Invite email+role, resend, revoke; plan, usage vs limits (UsageMeter), self-service upgrade, invoice list/download | Members see General; invites/billing per role matrix |
| `/invite/[token]` | Accept invitation | A2 | Validates token → reuses `/sign-up` with email pre-filled if no account → lands directly on the project; invalid/expired token screen | Public |
| `/help` | Interactive manual (recycled from `/manual`) | — | Versiona how-tos | Auth |

## 3. Component tree

New components under `frontend/components/`; UI kit is net-new (the template has none).

```
components/
├── ui/                      ← NEW base kit (HTML + Tailwind tokens; no Radix)
│     Modal · ConfirmDialog · Toaster+useToast · Tabs · Table · StatusBadge
│     EmptyState · Skeleton · Dropdown · Tooltip · ProgressBar · Avatar · Pagination
├── pdf/
│   ├── PdfViewer            ← react-pdf, next/dynamic ssr:false; takes a signed fileUrl
│   │   ├── ViewerToolbar    (page, zoom, fit, download, overlay toggles, "select zone" mode)
│   │   ├── PdfPageShell     (one per page; own IntersectionObserver, mounts visible ±2)
│   │   │   ├── <Page>       (react-pdf canvas + text layer)
│   │   │   └── PageOverlayLayer        (absolute; normalized bbox → CSS)
│   │   │       ├── ObservationAnchor   (pin/rect colored by state — D3)
│   │   │       ├── DiffHighlight       (added/removed/modified — E1, D5 evidence)
│   │   │       └── SectionBoundary     (line + label; hover → mini section history/blame — C3)
│   │   └── RegionSelector   (drag-rect in select mode → emits normalized bbox — D3)
│   └── ViewerProvider       (React context + useReducer, one PER viewer instance — see §4)
├── compare/                 ← E1 star screen
│   ├── CompareView
│   │   ├── CompareHeader            (base/target pickers, 3-view switcher, job badge)
│   │   ├── SideBySideView           (2× PdfViewer + SyncScrollController: syncs BY SECTION,
│   │   │                             not by pixel — robust to reflow; pure logic in lib/compare/sync.ts)
│   │   ├── SectionChangeList        (modified/added/removed/unchanged; click jumps both viewers)
│   │   └── ChangeSummary            (counts per type, affected seals (D5), check delta (E3))
├── versions/
│   ├── VersionTimeline / VersionTimelineItem  (author·date·message·ChecksTrafficLight·
│   │                                           SealsSummaryBadge·approved badge·download·compare)
│   ├── UploadDropzone       (drag&drop; validates .pdf + size client-side; presigned PUT with
│   │                         axios onUploadProgress; then job phases pending→running→done/failed+retry) — C1/C2
│   └── PostUploadSummary    (the C2 "git push" moment: what changed / checks / affected seals, in seconds)
├── review/
│   ├── ReviewRequestPanel   (D1: reviewers suggested from section owners, message, submit)
│   ├── ReviewContextBar     (D2: traffic light + change summary first; "next changed/red section";
│   │                         "already reviewed by you" marks from last seal vs diffs)
│   ├── InboxList / InboxItem (D1/D2/D5)
│   ├── observations/ ObservationsPanel → ObservationThread (states open/answered/resolved,
│   │                         reviewer+state filters) → ObservationComposer (D3)
│   ├── checks/ ChecksPanel → ChecksTrafficLight → CheckEvidenceLink (page+reason → jumps viewer) (E3)
│   └── seals/ SealsPanel → SealCard (valid | invalidated/requires-re-review |
│                 preserved-with-record | pending-confirmation — record shows origin version+date+evidence)
│             → SealActionBar (D4 one click) → InvalidationReviewCard (D5 coordinator:
│                 proposal with per-section diff evidence + Confirm/Reject)
├── projects/  ProjectsBoard · ProjectCard · ProjectFilters · ProjectSearch · ProjectForm · SettingsTabs (B3)
├── onboarding/ OnboardingWizard (4 steps, progress persisted server-side — A1)
└── org/       MembersTable · InviteForm (A2) · BillingPanel · UsageMeter · InvoicesTable (F1)
```

**PDF viewer library — `react-pdf`** (bundles a pinned `pdfjs-dist`): declarative
`<Document>/<Page>`, built-in text layer (selection, search, accessibility), viewport/scale
resolved, active maintenance, React 19-compatible; needs worker config + `ssr:false` via
`next/dynamic`. Raw `pdfjs-dist` would mean weeks of canvas plumbing for control we do not
need. Page virtualization: own IntersectionObserver (visible ± 2 pages) — no `react-window`
until >150-page documents show up (DP-16).

**Coordinate contract with the backend** (fixed, reconciled): all anchors/bboxes travel
**normalized 0–1, top-left origin**, canonical shape `{page, x0, y0, x1, y1}`. Frontend
converts to CSS with the pure function `bboxToCss(bbox, pageW, pageH)` in `lib/pdf/coords.ts`
(100%-testable); the backend converts from PDF points (bottom-left) exactly once at indexing.

## 4. State management

New Zustand stores (template `productStore` pattern: state + `loading` + `error` + actions +
exported selectors):

| Store | Responsibility |
|---|---|
| `orgStore` | Active org, memberships, effective role, plan limits (F1 gating), org switch |
| `projectStore` | Board list (server-side filters/search — B2), detail, create (B1), settings (B3) |
| `documentStore` | Documents per project, upload orchestration (C1/C2; upload % separate from job state) |
| `versionStore` | Timeline (C3), active version (meta + sections + bboxes), signed download URL |
| `jobStore` | **Generic** job tracker: `jobs: Record<jobId, {type, status, progress, error, result_ref}>`; `track(jobId)` starts polling — 2 s → ×1.5 backoff to 10 s, stops on done/failed or 5-min timeout (StagingGate pattern) |
| `compareStore` | base/target pair, result (section_changes + highlights + summary), active view (E1) |
| `observationStore` | Hilos por versión y estado, páginas de respuestas/historial, contenido íntegro por partes y create/reply/transition (D3). Descarta respuestas tardías al cambiar versión o filtro. |
| `reviewStore` | Requests (D1), inbox, "already reviewed by you" progress (D2) |
| `sealStore` | Seals per version with validity states, seal action (D4), invalidation plan + confirm (D5) |
| `checkStore` | Checklist config (E3/B3) + per-version results with evidence |
| `billingStore` | Plan, usage, checkout, invoices (F1) |
| `uiStore` | Toast queue, active modal |

Kept: `authStore`, `localeStore`, `stagingBannerStore`. Deleted: `productStore`, `blogStore`,
`cartStore`.

**Viewer state is NOT global**: current page, zoom, fit mode, selection mode and in-progress
bbox live in a `ViewerProvider` (React context + useReducer) **per PdfViewer instance** —
CompareView mounts two independent viewers; `SyncScrollController` talks to both contexts from
above. Zustand holds remote data only.

**Async jobs: POLLING** (decision): the template already proves the pattern (StagingGate); the
backend is WSGI/gunicorn (SSE would demand ASGI/long-lived workers with no flow paying for
it); jobs last seconds and state lives in the DB; trivially testable with
`jest.useFakeTimers()` and `page.waitForResponse`. SSE/WebSockets noted for V2 (live
collaboration on D3).

## 5. API contract per screen

Endpoints from `03-backend.md`; jobs polled via `GET /api/jobs/{job}/`.

| Screen | Consumes | Purpose |
|---|---|---|
| Onboarding (A1) | `POST orgs/` · `POST orgs/{org}/sample-project/` → 202 job · job polling | Name org; seed sample project; resume wizard |
| Projects board (B2) | `GET orgs/{org}/projects/?q=&status=` · `GET search/documents/?q=` | Cards + filters; content-search toggle |
| Create project (B1) | `POST orgs/{org}/projects/` (402/409 → upgrade modal) | 30-second create |
| Project view | `GET projects/{proj}/` · `GET projects/{proj}/documents/` · `GET/POST projects/{proj}/members/` | Detail, documents, team |
| Project settings (B3/E3) | `GET/PUT projects/{proj}/config/` | Checklist, owners, approval rules, `d5_mode` — creates a new config version |
| Upload (C1/C2) | `POST documents/{doc}/versions/upload_intent/` → presigned PUT (axios progress) → `POST .../versions/complete/` → 202 {version_id, job_id} → job polling | Two-step upload (DP-06) |
| Timeline (C3) | `GET documents/{doc}/versions/` · `GET versions/{ver}/download/` | History; signed download |
| Version viewer | `GET versions/{ver}/` · `/sections/` · `/checks/` · `/seals/` · `/observations/?reviewer=&status=` | Render + the three side tabs |
| Compare (E1) | `POST documents/{doc}/comparisons/` (200 cache \| 202 job) · `GET comparisons/{cmp}/` · `GET comparisons/{cmp}/sections/{sec}/diff/` | Star screen, three views, fine diffs |
| Review request (D1/D2) | `POST versions/{ver}/review_requests/` · `GET review_requests/{id}/` · `GET review_requests/{id}/progress/` | Request, detail, "already reviewed by you" |
| Inbox | `GET me/review_inbox/` · `GET me/notifications/` | Assignments, re-reviews, confirmations |
| Seals panel (D4/D5) | `POST versions/{ver}/seals/` · `GET versions/{ver}/seals/` · `GET versions/{ver}/seal_plan/` · `POST versions/{ver}/seal_plan/confirm/` · `POST seals/{seal}/revoke/` | One-click seal; validity states + records; coordinator confirmation |
| Observations (D3) | `POST versions/{ver}/observations/` · `POST observations/{obs}/replies/` · `POST observations/{obs}/status/` | Anchor, thread, state cycle |
| Org members (A2) | `GET/POST orgs/{org}/invitations/` · `GET invitations/{token}/` · `POST invitations/accept/` · member PATCH/DELETE | Invite → accept → land on project |
| Billing (F1) | `GET plans/` · `GET orgs/{org}/subscription/` · `POST .../subscription/checkout/` · `GET orgs/{org}/invoices/` + download | Limits, upgrade, invoices |

## 6. Open questions (DECISIÓN PENDIENTE)

| ID | Question | Recommendation |
|---|---|---|
| DP-15 | Routes: flat + `orgStore` vs `/o/[orgSlug]/...`. | **Flat** in MVP (typical user is mono-org); slug added in V2 if multi-org gets heavy — `proxy.ts` guard unchanged. |
| DP-16 | Page virtualization: own IntersectionObserver vs `react-window`. | Own (±2 pages); revisit at >150-page documents. |
| DP-17 | i18n: activate `next-intl` (declared but unused in the template) vs keep the custom `localeStore`. | **MVP is Spanish-only UI** with per-module TS string dictionaries + existing `localeStore`; activate next-intl only when an English-speaking customer appears (avoids `[locale]` route segments now). |
| DP-18 | Viewer accessibility depth. | react-pdf text layer (read/select) + keyboard navigation in SectionChangeList + `aria-live` job states; add `@axe-core/playwright` smoke in It4. |
