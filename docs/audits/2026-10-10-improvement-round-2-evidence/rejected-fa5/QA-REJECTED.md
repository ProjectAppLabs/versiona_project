# QA delegada — REJECTED

Ronda: `versiona-20261010-ronda2`. Codebase: `versiona_project`.
SHA probado: `fa5a3f7a805022df46dafd5223bbb8a237b529f2`. Árbol: `6c1c9eb996bf1564cd0d673564a73a955ff6a311`. Limpio antes y después; sin cambios versionados de QA.

## Resultado

106 casos reales verdes: 68 backend (42 Seguridad y 26 Observabilidad), 26 unit y 12 E2E. Cero skips y retries en las ejecuciones requeridas. La ronda se rechaza exclusivamente por el gate backend obligatorio: 29 errores de Ruff, todos en el test de revisores; el módulo nuevo de Observabilidad no tiene findings.

| Candidato | Ejecuciones reales | Gate |
|---|---:|---|
| I-S-0c3b90d936f0 | 42 backend | Rechazado: 29 errores de lint heredados |
| I-M-0c0b8831bfb6 | 26 unit + 12 E2E | Unit y C3: exit 0, AST completo |
| I-O-42a58784c64c | 26 backend | Módulo sin findings; gate backend conjunto rechazado |

Architect y Auditor: APPROVED en revisión estática, sin REWRITE/MERGE/DELETE. Esto no sustituye el gate ejecutado. No se registró ningún candidato como verified.

C3: required y satisfied = display/failure/success, covered, junk_only/unvalidated vacíos. E2E acredita canvas, PDF v2 distinguible, 503 sin PDF previo y reintento real exitoso. E1 conserva regresión de cinco viewports. D5 sigue parcial (success cubierto) y admin handoff exento: no son nuevas tareas.

## Comando del gate rechazado

```bash
PATH=/tmp/versiona-improvement-10102026/venv/bin:$PATH python3 scripts/test_quality_gate.py --repo-root . --suite backend --semantic-rules strict --junk-severity error --external-lint run --include-file backend/reviews/tests/test_review_request_edges.py --include-file backend/public_tools/tests/test_public_processing_diagnostics.py --report-path frontend/test-results/improvement/versiona-20261010-ronda2/quality-backend-canonical.json --no-color
```

Exit code 1; 2 archivos analizados, 29 tests estáticos, 29 errores, 1 warning y 1 info. Ruff realmente disponible: status ok. Warning: ocho aserciones en test de admin implícito; no se propone modificarlo.

## Contraste con base

Base dac8de2: 30 findings de Ruff; SHA fa5: 29. Los 29 actuales tienen el mismo rule y función/docstring/import en el blob base. Cero findings en funciones nuevas. En el bloque de imports I001 ya existía; su texto cambió por los imports nuevos. Comparación realizada con mismos selectors oficiales y stdin-filename del archivo real, sin cache.

| Regla | Línea actual | Línea base | Función o bloque |
|---|---:|---:|---|
| D205 | 1 | 1 | `module_docstring` |
| D209 | 1 | 1 | `module_docstring` |
| I001 | 4 | 4 | `module_imports` |
| D103 | 21 | 17 | `ready_version` |
| D103 | 27 | 23 | `open_review` |
| D103 | 38 | 34 | `test_reviews_list_returns_requests_with_assignments` |
| D103 | 53 | 49 | `test_second_open_request_via_api_returns_conflict` |
| D103 | 70 | 66 | `test_requester_cancels_open_review_via_api` |
| D103 | 85 | 81 | `test_cancel_unknown_review_returns_404` |
| D103 | 97 | 93 | `test_cancel_already_closed_review_returns_conflict` |
| D103 | 113 | 109 | `test_review_context_endpoint_returns_empty_payload_without_seal` |
| D103 | 124 | 120 | `test_review_request_requires_analyzed_version` |
| D103 | 143 | 139 | `test_review_request_on_trashed_version_is_rejected` |
| D103 | 159 | 155 | `test_review_request_without_reviewers_is_rejected` |
| D103 | 325 | 181 | `test_non_requester_reviewer_cannot_cancel_review` |
| D103 | 335 | 191 | `test_admin_who_did_not_request_can_cancel_review` |
| D205 | 361 | 217 | `test_section_owners_do_not_make_reviewer_selection_optional` |
| D209 | 361 | 217 | `test_section_owners_do_not_make_reviewer_selection_optional` |
| D205 | 378 | 234 | `test_section_owners_are_not_added_as_reviewers_on_their_own` |
| D209 | 378 | 234 | `test_section_owners_are_not_added_as_reviewers_on_their_own` |
| D205 | 398 | 254 | `test_assignment_scope_ignores_the_sections_the_reviewer_owns` |
| D209 | 398 | 254 | `test_assignment_scope_ignores_the_sections_the_reviewer_owns` |
| D205 | 412 | 268 | `test_review_progress_route_is_not_registered` |
| D209 | 412 | 268 | `test_review_progress_route_is_not_registered` |
| D205 | 421 | 277 | `test_assigned_reviewer_hits_a_missing_progress_endpoint` |
| D209 | 421 | 277 | `test_assigned_reviewer_hits_a_missing_progress_endpoint` |
| PT006 | 433 | 289 | `test_review_context_permission_matrix` |
| D205 | 441 | 297 | `test_review_context_permission_matrix` |
| D209 | 441 | 297 | `test_review_context_permission_matrix` |

## Por qué pasó CI

CI real del PR #67, run 38070254601, contiene Ruff status unavailable: "ruff executable not found in PATH"; findings 0. Reporte global: errors 0, warnings 61. Workflow instala npm pero no Ruff; scripts/test_quality_gate.py:666 clasifica unavailable como warning y :1482 sólo falla por warnings con --strict, opción que CI no usa. El gate local con Ruff sí observa 29 errores. No es un problema del filtro acotado. JSON CI externo se conserva únicamente como diagnóstico de paridad, nunca como ejecución QA de este SHA.

Referencia: https://github.com/ProjectAppLabs/versiona_project/actions/runs/38070254601/job/114266024404

## Evidencia

Manifest rechazado: `frontend/test-results/improvement/versiona-20261010-ronda2/qa-manifest-fa5a3f7-rejected.json`.
Comandos y resultados originales del Verifier: `executions.json`.
Playwright JSON real: `playwright-results.json`; copia exacta con hashes en `playwright-copy-proof.json`.
JSON Jest originales + JUnit derivado: `unit-*.json/xml`; hash de entradas/salidas/conversor en `jest-conversion-proof.json`.
Servidor del SHA limpio: `live-server-proof.json`.
Flow audit y contraste: `flow-audit.json`, `flow-c3-verification.json`, `ruff-base-comparison.json`.

## Comprobaciones auxiliares

- Exit 0: `npm ci`. 741 packages installed; no lockfile mutation
- Exit 0: `npx tsc --noEmit`. 
- Exit 0: `npm run lint`. 16 warnings, 0 errors; includes react-hooks/set-state-in-effect at page.tsx:71
- Exit 1: `python3 scripts/test_quality_gate.py --repo-root . --suite backend --strict --semantic-rules strict --junk-severity error --external-lint run --include-file backend/reviews/tests/test_review_request_edges.py --include-file backend/public_tools/tests/test_public_processing_diagnostics.py --report-path frontend/test-results/improvement/versiona-20261010-ronda2/quality-backend.json --no-color`. auxiliary pre-canonical attempt: ruff unavailable on PATH and strict escalated warnings
- Exit 1: `npm test -- 'app/projects/[projectId]/documents/[docId]/versions/[versionId]/__tests__/page.test.tsx' --json --outputFile=test-results/improvement/versiona-20261010-ronda2/unit-version-page.json`. selection attempt only: Jest glob interpreted bracketed route segments; executed zero tests; corrected with --runTestsByPath

ESLint global: 0 errores, 16 warnings, incluido set-state-in-effect page.tsx:71. No se propone refactorizar ese advisory. Mutación no configurada. Los intentos NoTestsFound (0 casos) y gate sin Ruff/--strict incorrecto permanecen registrados; no se cuentan como pruebas verdes.

## Continuación

Devuelto al dueño de Seguridad el lint de su test. El conductor coordina el commit y la integración. La evidencia fa5 queda ligada a fa5 y rechazada; un SHA nuevo requiere evidencia nueva, sin relabelar estos resultados. Servicios y evidencia privados se conservan hasta aviso del conductor.
