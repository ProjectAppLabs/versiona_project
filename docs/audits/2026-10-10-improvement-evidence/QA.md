# Evidencia exportada de QA

Esta copia corresponde al commit exacto `bdd1994e938f7f0e3138f21b699bdd8aad4de8d8`. Los artefactos son salidas reales saneadas; los logs completos y los intentos fallidos quedan fuera de los archivos versionados. `provenance.json` conserva hashes originales y exportados. El registro es local de Versiona y no actualiza el ledger del toolkit.

# QA combinada — improvement-10102026

Veredicto: **APPROVED**, exclusivamente para los tres candidatos y el commit bdd1994e938f7f0e3138f21b699bdd8aad4de8d8.

Worktree: /home/dev_env/webapps/.wt/versiona_project/queue-10102026-1423. Árbol b5d4451e7aef836973c8581407d8f34e5869286b. Base f0c111980447ab880db4c369eec9f5c29594a94a. No autoría de aplicación, tests, configuración, Git ni toolkit en esta fase.

## Alcance y evidencia candidata

| Candidato | Conducta observada | Ejecuciones reales |
|---|---|---|
| I-S-3b550c956232 | Recuperación por correo antes de vincular Google; vinculación explícita; revocación de access/refresh/desafíos por época; continuidad de onboarding y conservación de TOTP | Google Link 20; JWT/onboarding 15; unit 18+10+17+16+13; E2E 13 |
| I-P-108f9bbe38dd | Reanclaje por lotes acotados; presupuestos de consultas; concurrencia, rollback, idempotencia y regresores de D5 conservados | Backend 19 |
| I-O-f5de8573e07a | Mailpit rechaza HTTP fallido/respuesta inválida; ausencia sólo en respuesta válida vacía; purge exige éxito | Unit 6 |

**147 pruebas aprobadas: backend 54, frontend-unit 80 y E2E 13. Ningún fallo, omisión ni reintento en el manifiesto candidato.** Los comandos literales, códigos reales de salida y asociaciones están en manifest.json y los *.meta.json; resultados originales en XML/JSON regulares.

Backend: backend-google-link.xml (20), backend-jwt-onboarding.xml (15), backend-reanchor.xml (19). Unit: unit-security-panel-ticket.xml (18), unit-forgot-password.xml (10), unit-sign-in.xml (17), unit-sign-up.xml (16), unit-http.xml (13), unit-mailpit.xml (6).

E2E: e2e.json, 13 expected, 0 skipped/unexpected/flaky/errors; exit 0, duración 169542 ms. Dos archivos: auth/auth.spec.ts y app/onboarding/a3-account-security.spec.ts; CI=1, retries=0, un worker, servidores nuevos y sin E2E_REUSE_SERVER. e2e-runtime.json acredita puertos 8120/3120 y cwd backend/frontend del worktree exacto. MySQL 3312, Redis 6382, Mailpit HTTP 8027/SMTP 1027, DB/storage privados. El harness sustituye únicamente las fronteras externas de Google; API, tokens, permisos, correo y persistencia reales. Sin migrate directo ni datos desplegados.

## Gate oficial y flujos

| Capa | Archivos realmente escaneados | Tests estáticos | Errores | Advertencias |
|---|---:|---:|---:|---:|
| Backend | 10 | 139 | 0 | 18 |
| Frontend unit | 9 | 96 | 0 | 5 |
| Frontend E2E | 2 | 12 | 0 | 0 |

Gate oficial test_quality_gate.py, reglas semánticas strict, junk-severity=error, lint externo run; los tres códigos de salida son 0, infraestructura sin errores e include-files sin ignorar. E2E conserva una excepción preexistente allow-no-interaction para el guard que actúa al navegar; no se añadió ninguna excepción en esta ronda. El número estático de tests difiere de casos parametrizados ejecutados; no constituye evidencia de ejecución. Artefactos gate-backend.json, gate-frontend-unit.json y gate-frontend-e2e.json. Las advertencias quedan visibles; no justifican autoría adicional sin un fallo concreto.

flow_coverage_audit.py: exit 0; 34 specs, 95 tests estáticos, 40 flows; 38 covered, 1 partial, 0 missing, 1 exempt. flow-audit.json conserva el resultado completo. A1/onboarding y A3/security se contrastaron con los flujos reales por Architect y la revisión e2e-user-flows-check. El viaje nuevo recorre preregistro→correo→recuperación→login→vinculación→revocación; los dos casos de rutas Google parametrizadas sí se ejecutaron y pasaron. El clasificador estático marca su título interpolado como untagged; las etiquetas/resultados reales están en e2e.json.

## Auditoría conductual

Auditor mantiene KEEP para los tres candidatos tras comprobar: refresh disponible antes de exigir ausencia de replay; access no vacío y admitido con 200 antes del 401 posterior; secreto/timestamp TOTP exactamente conservados; tickets válidos acreditados antes de rechazar expiración/eliminación. El cuerpo de la precondición Mailpit no contiene if; no se autorizó trasladar assertions sin un defecto demostrado. Verifier confirma las ejecuciones, gates y flow audit. No herramienta de mutación configurada: no se afirma una puntuación de mutation testing.

## Límites, incidencias y deuda separada

- El alcance es la ronda de tres candidatos. No certifica toda la aplicación ni convierte los diagnósticos de otros frentes en validaciones completas.
- D5-selective-invalidation permanece partial en el inventario global: outcomes display/failure no satisfechos. auth-admin-login-handoff está exempt. Estos estados no se atribuyen al cambio ni se declaran cerrados. La interpretación de preservación manual de D5 sigue needs-evidence, sin modificación.
- Preflight readonly informó un mapa stale por backend/**/views/*.py, patrón que incluye backend/accounts/tests/views/*.py. Las razones corresponden a cinco tests, no a rutas productivas posteriores al mapa. Architect contrastó los flujos reales; no se regeneró mapa ni se invocó Analyst por este falso positivo.
- Regresión auxiliar authStore ejecutada con filtros y omisiones expresas, fuera del manifiesto formal:
- aux-auth-store-session: 8 aprobados; 16 omitidos por filtro. XML real separado del manifiesto.
- aux-auth-store-linking: 7 aprobados; 17 omitidos por filtro. XML real separado del manifiesto.
  Cobertura auxiliar única: 15 de 24 casos; no se afirma suite completa.
- El primer arranque E2E de este SHA ejecutó cero casos por nombres de variables incorrectos en el handoff del orquestador. Se preservó e2e-attempt-env-1/ (exit 1). Se corrigió sólo el comando a E2E_GOOGLE_HARNESS_DB_NAME y E2E_GOOGLE_HARNESS_STORAGE_ROOT; no configuración, guards ni timeouts. El manifiesto incluye exclusivamente la posterior ejecución real aprobada.
- Evidencia previa 519e2ad y el lote B1 del intento 5e3ba0a se preservan separados y no se atribuyen al SHA final. El lote previo de seguridad de 21 casos incumplió el límite; no se reutiliza como evidencia final. Todos los lotes candidatos finales tienen como máximo 20 casos, ciclos de hasta tres comandos y E2E de dos archivos, posterior a backend/unit sin carga propia concurrente.
- No se ejecutaron qa-agent --check/--verify ni el CLI --validate-qa ni se escribió ledger canónico. verification.validate_verification se usa en modo lectura contra round-local.json; su aceptación local no equivale al estado canonical ledger verified ni certifica CI remoto/merge.

## Artefactos para el conductor

Todos bajo test-results/improvement/2026-10-10-final/: qa.md; manifest.json; round-local.json; verification.json; gate-backend.json; gate-frontend-unit.json; gate-frontend-e2e.json; flow-audit.json; los nueve XML candidatos arriba; e2e.json; e2e-runtime.json. Logs originales y metadata de cada comando se conservan ignorados; exportar únicamente evidencia saneada y repetir verificador oficial sobre los archivos exportados.

Verificación final: verification.json registra valid=true del módulo oficial para esta ronda/SHA y sus 13 ejecuciones. git-final.json acredita HEAD exacto, status limpio y artefactos regulares ignorados. Ninguna brecha bloqueante abierta en los tres candidatos. APPROVED no acredita merge ni CI remoto.
