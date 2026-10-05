# Active Context — Versiona

> Memory Bank core file: current focus, recent changes, next steps. Updated every session
> that changes project state.

**Last updated**: 2026-10-02

## Autenticación y purga por lotes (2026-10-02)

La ruta JWT alternativa exige la misma admisión de cuenta y TOTP que el acceso
habitual, antes de crear tokens. Las entradas de autenticación comparten la cuota
configurada por IP; la caché sigue siendo local por proceso y requiere Redis y
verificación del proxy antes de tráfico real. La purga recorre raíces y
descendientes en lotes de 100 por clave creciente, conservando borrados por
instancia, contadores, triggers y protección de certificados.

Se trabaja en `fix/02102026-improvement-auth-purge`, separada del checkout del
servicio, sobre `master`. QA combina API y los recorridos existentes A1/A3 contra
un MySQL privado en puerto 3310 y schemas de prueba. Los resultados del commit
final y el PR se registran en el toolkit:
`docs/audits/2026-10-02-versiona_project_staging-improvement-pass-project-auth-purge.md`.
La selección sigue limitada a tres causas; los cinco frentes conservan alcance
parcial y pendientes explícitos.

## Contraseñas y diagnóstico de rendimiento (2026-10-02)

Ronda independiente desde `master`, en el worktree propio
`improvement-password-profile`. Registro, cambio autenticado y recuperación
validan la contraseña con la política configurada de Django y los atributos del
usuario. Un rechazo conserva la contraseña vigente y el código de recuperación;
el cliente sigue recibiendo un error de texto con HTTP 400.

El cupo global comprende una corrección (`I-S-0c3d7ee8c75e`) y dos diagnósticos
(`I-P-b9b80760481e`, `P-backend-views-01`). En los escenarios acordados, el historial
de observaciones excede los presupuestos de respuesta y memoria instrumentada;
el reporte consulta por documento y por su cadena de validez. Ambos permanecen
pendientes de optimización, con contrato y reglas D5 intactos. Ningún frente
queda declarado suficiente.

QA de esta ronda combina pruebas de API y navegador con MySQL y Mailpit privados.
Su ejecución final se liga al commit limpio de aplicación y tests; el reporte
canónico conserva el resultado y las mediciones:
`docs/audits/2026-10-02-versiona_project_staging-improvement-pass-project-password-profile.md`
en el toolkit. La entrega corresponde a un PR propio abierto hacia `master`,
con CI verde, sin merge ni cambios en el checkout del servicio.

## Ronda transversal de mejora (2026-10-01)

Implementadas sobre la rama propia del PR #34: identidad Google vinculada a
claims verificados, segundo factor obligatorio en ese acceso y análisis
recuperable desde fases confirmadas. El motor común eligió tres causas globales
(`I-S-cae2f9667fc6`, `I-S-f775b80c4455`, `I-O-478a8866d0d5`).
La autoría de QA incluye claims inválidos, desafíos vigentes, pantallas de
código y recuperación por fase. La evidencia de ejecución y entrega del SHA
final se conserva en el reporte canónico del toolkit:
`docs/audits/2026-10-01-versiona_project_staging-improvement-pass-project-transversal.md`. El entorno de pruebas usa un MySQL privado en el puerto 3309 y schemas
propios, sin reutilizar la base del deploy. Los demás hallazgos quedan pendientes
por cupo o por evidencia; esta ronda no declara suficiente ningún frente.

## Rendimiento, responsividad y QA (2026-09-30)

Ronda aplicada sobre una base aislada: la línea de tiempo de versiones obtiene la
misma información visible con relaciones y resúmenes de checks precargados, y la
limpieza de comparaciones públicas vencidas avanza en lotes acotados sin cargar
sus resultados JSON. En el módulo de proyectos, filtros, formularios, ajustes e
invitaciones respetan controles táctiles y envuelven los textos largos sin cambiar
la distribución de cinco columnas del checklist que ya cabe en tableta vertical.

QA confirmó 18 casos pytest y 9 Playwright, con el control estricto de los cinco
archivos tocados sin errores ni advertencias. Los recorridos propietarios B2, B3
y A2 se ejecutaron sobre la base privada de la sesión, incluyendo entrega de correo
y lectura del token en un buzón local. Entrega: [PR #34](https://github.com/ProjectAppLabs/versiona_project/pull/34) hacia master. El `Header` compartido conserva un overflow horizontal
preexistente en ancho compacto; se registró para una futura ronda de layout y no
se atribuye al módulo de proyectos. La lista general de documentos quedó
diagnosticada: su autorización compartida excedía el presupuesto de esta ronda.

## Ronda de cobertura total de escenarios (2026-07-23)

Segunda sesión del día, sobre el pipeline ya mergeado (PR #2). Objetivo: que cada
user flow tenga prueba **en la capa que el mapa exhaustivo prescribe**, no solo un
spec por flujo. Punto de partida: 170 ids en `docs/audit/03`, 64 sin rastro alguno.
Resultado: **191 de 192 ids con prueba**; el único sin ella es `A1-L01` (métrica de
activación, sin superficie testeable). 47 marks de trazabilidad + 55 tests backend
+ 24 RTL + 2 escenarios E2E; el mapa ganó §7.bis (superficies públicas It9, clases
`T`/`S`) y §10.bis (15 divergencias mapa↔código auditadas).

**Hallazgos de producto abiertos** (ninguno arreglado: ronda de solo-tests) —
detalle en §10.bis: la bandera `degraded` nunca se persiste ⇒ DP-09 no fuerza
coordinador · sin guarda de "rojo estructural" (una versión sin secciones sigue
siendo sellable) · `Document.approved_version` es campo muerto · el DELETE de
comparaciones guardadas ignora autoría y borra todas las filas · el salto de un
check rojo a su sección no existe en la UI · sin API de reenvío de invitación ni
de remoción de miembro · `onboarding_state` sin estado de fallo (500 al usuario).

## Current focus

**Quality pipeline session (2026-07-23) on top of the merged It0–It9 product**: the 8
project skills ran as sequential phases — methodology refresh, domain-true fake data
(create seeds through ensure_personal_org; delete honors protected evidence I4),
flow audit (caught the unregistered F3 org-audit flow), dev-DB refresh + e2e re-seed,
backend coverage tail to ~100 per file with all 14 apps finally measured
(public_tools tests were silently uncollected in CI), frontend stores/staging/manual
to 100 lines, quality gate at 0 errors / 0 warnings, and e2e flow coverage 37/37.
Two production fixes fell out: trash restore slug-collision ordering and the
E2E harness ports (env-parameterized after a foreign fleet server squatted :3000).

## What a fresh session should know

- Plan state: `Organization.plan` (console override, always wins) +
  `billing.Subscription` (trial). Read plans ONLY through
  `billing.services.effective_plan` / `usage_report`.
- The ONLY AllowAny surfaces: auth, invitation_state, `GET /api/public/plans/`,
  `POST/GET /api/public/comparisons/` (app `public_tools`, ephemeral by design).
- Engine's `analyze_bytes(data, allow_ocr=True)`: the flag exists for the anonymous
  comparator; authed paths never pass it explicitly (byte-identical behavior).
- Frontend public routes: `/`, `/precios`, `/comparar[/:id]`, `/manual`, auth pages.
  `publicApi` (no interceptors) is the client for AllowAny endpoints.
- Flow contract: `frontend/e2e/flow-definitions.json` v2.2.3 — 37 flows; f1-billing is
  honestly scoped (no online checkout).

## Next steps (operator-gated — in order of launch impact)

1. Execute deferred deployment (DP-21): nginx + systemd (gunicorn/celery/beat) + SSL.
2. DP-22: domain + production SMTP (today only mailpit dev).
3. Rotate the Ed25519 dev signing key + secret-manager custody (DP-24) — before the
   first regulated customer.
4. Wompi keys → build the checkout leg over the existing trial/limits scaffolding (F1
   payment; webhook throttle scope already reserved).
5. Optional growth (It10 candidates): public certificate verification page
   (/verificar/<code> + QR — the trust/viral loop deferred from It9), SSO (A3),
   Redis-backed throttles, annual pricing.

## Recent decisions to keep in mind

- Trial: 14 days (settings.BILLING_TRIAL_DAYS), auto-start on personal-org creation
  ONLY (existing orgs never get one retroactively); expiry is lazy + daily beat
  `billing-trials-daily` (13:00 UTC ≈ 08:00 Bogotá) for notices.
- Anonymous comparator: files are EPHEMERAL (deleted in the task's finally + hourly
  purge), results expire in 24h; no OCR for anonymous users (422 upsell instead).
- Free limits unchanged (1 project / 2 members / 30-day history, DP-04 lock-never-
  delete) — no new metering this cycle by operator decision (2026-07-22).
- No fake trust signals on marketing surfaces (operator-aligned honesty rule).
