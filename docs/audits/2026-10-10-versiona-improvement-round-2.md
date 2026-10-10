# Versiona — segunda ronda de mejora del 2026-10-10

Estado: tres causas implementadas y QA APROBADA del commit `8611077`.
La aceptación canónica y sus artefactos se publican antes de iniciar merge-queue;
el estado de integración se acredita con los cuatro PR y el cierre del orquestador.

Base común: `dac8de2c8959c9b379186543b0f1d4d16a8f1c13` (`master` remoto).
El clon de deploy permanece en `492af1e`, limpio y sin checkout ni edición.
Las ocho sesiones anteriores quedan fuera del alcance de esta ronda.

## Decisión

El operador autorizó tres causas globales. Cada archivo tiene un único dueño;
los agentes implementan y commitean sus frentes, y el orquestador posee los
registros compartidos, push, PR, integración y cierre. El criterio es impacto
ALTO, o MEDIO con esfuerzo BAJO y riesgo BAJO. No se añaden mejoras por volumen.

| Frente | Estado | Decisión |
|---|---|---|
| Seguridad | VALE LA PENA | Rechazo uniforme de revisores inexistentes o sin acceso. |
| Mantenibilidad | VALE LA PENA | Identidad y respuestas vigentes del visor de versiones. |
| Observabilidad | VALE LA PENA | Diagnóstico saneado de fases del comparador público. |
| Rendimiento | VALE LA PENA | Reutilizar snapshots, pendiente por el cupo. |
| Responsividad | NO VALE LA PENA | No aplicar sin evidencia visual del SHA actual. |
| QA | VALE LA PENA | D5/inbox y Mailpit directo de M1 pendientes por cupo; valida las causas aprobadas. |

| ID | Dueño | Impacto | Esfuerzo | Riesgo |
|---|---|---|---|---|
| `I-S-0c3b90d936f0` | Seguridad | ALTO | BAJO | BAJO |
| `I-M-0c0b8831bfb6` | Mantenibilidad | ALTO | MEDIO | MEDIO |
| `I-O-42a58784c64c` | Observabilidad | MEDIO | BAJO | BAJO |

El motor canónico se usa para previews y para un ledger local bajo los
artefactos ignorados de Versiona, mediante `IMPROVEMENT_LEDGER_DIR`. Los previews
por alcance confirman `proceed` de Seguridad y Mantenibilidad. Observabilidad
reutiliza el ID previo y requiere revalidar el contexto obsoleto con el código
y las pruebas de esta ronda. El preview general contiene causas históricas del
ledger que ya no corresponden al código: no se adoptan como trabajo nuevo.
El toolkit no se edita ni se pushea; decisiones y evidencia se entregan en
Versiona. La verificación local no adjudica `verified` a su ledger externo.

## Contratos y límites

**Seguridad.** La selección consultaba usuarios globales y distinguía un ID
inexistente de un usuario ajeno, incluyendo su correo en el rechazo
(`backend/reviews/services/review_service.py:39-46`, base indicada). El rechazo
aprobado es HTTP 404, payload `{"error":"Revisor no encontrado."}`, para ambos.
Se comprueba acceso de todos los candidatos antes de rol o autorrevisión;
se preservan roles owner/admin implícitos y errores 400 de candidatos visibles.

**Visor.** El store podía conservar la URL anterior cuando fallaba el siguiente
archivo y admitir respuestas obsoletas. El render debe asociar detalle y PDF
con la versión solicitada. Se separan carga/errores de detalle y archivo,
se descartan respuestas reemplazadas y se añade reintento de archivo. Los
retornos independientes del comparador y los avisos 402 vigentes se conservan;
un intento reemplazado de una versión no abre un aviso tardío.

**Observabilidad.** `run_public_comparison` guardaba `processing_failed` y
retornaba sin diagnosticar la excepción. El cambio aprobado registra un ERROR
con fase `read_a`, `read_b`, `build_result` o `persist_result` y clase de error.
No registra mensajes originales, traceback, IDs, nombres, keys ni contenido.
Conserva estados, cleanup y el tratamiento esperado `ocr_required`.

## Propiedad

- Seguridad: `backend/reviews/services/review_service.py` y
  `backend/reviews/tests/test_review_request_edges.py`.
- Mantenibilidad: `frontend/lib/stores/versionStore.ts`, página de versión,
  tests de versionStore, versionStore.historyLock y página, y el spec existente
  `frontend/e2e/app/documents/c3-version-history.spec.ts`.
- Observabilidad: `backend/public_tools/tasks.py` y nuevo
  `backend/public_tools/tests/test_public_processing_diagnostics.py`.
- Compartido: `frontend/e2e/flow-definitions.json`, `docs/USER_FLOW_MAP.md`,
  este reporte y evidencia saneada de la misma ronda.

C3 conserva ID, roles y prioridad y declara `display/failure/success`.
Versiona usa registro monolítico: USER_FLOW_MAP se actualiza directamente;
su generador no produce ese documento. El CI permite PR independientes del
visor y del mapa; la unión se valida antes del merge y el visor se integra
antes de compartido. No se afirma cobertura sólo por declarar los outcomes.

## Validación requerida

Antes de cada corrección se exige un regresor rojo ejecutado contra el código
base real. Luego se ejecutan pruebas del dueño y una única QA conjunta sobre
un commit limpio que contenga aplicación, tests y contrato de flujos.

Seguridad acredita privacidad, precedencia de rechazos, permisos conservados y
estado persistente sin efectos secundarios. Observabilidad acredita ocho
escenarios, sin sustituir build_result/analyze_bytes/save: storage y pipeline
reales, fallo SQL único, timeout en frontera externa y logs saneados con DB y
cleanup observables. El timeout no acredita un límite real de worker y el
fallo SQL recuperable no acredita recuperación de una caída completa de MySQL.

Frontend-unit usa promesas controladas y estado aislado; C3 en vivo debe mostrar
error de archivo, reintento correcto y un PDF v2 distinguible por su contenido
«8. PROTECCION DE DATOS PERSONALES» dentro del visor, además de página/canvas.
E1 se ejecuta sólo como regresión, sin modificar el spec ni el comparador.
El auditor debe acreditar específicamente los tres outcomes C3; D5 parcial y
admin handoff exento permanecen registrados como contexto histórico.

Se usan MySQL/Redis/Mailpit/storage privados, sin manage.py migrate ni .env de
producción. Máximo veinte casos por comando, tres comandos por ciclo y dos specs
por ejecución E2E; cero retries. El archivo de revisores ya supera veinte casos
antes de agregar pruebas: se divide por node IDs reales.

## Diferidos y descartes

Pendientes por cupo, no por bajo retorno:
- Reutilizar los snapshots de ambas versiones reduce cuatro lecturas a dos;
  falta medir SQL, CPU y memoria reales antes de afirmar una ganancia de latencia.
- D5 puede certificar ausencia del inbox mientras éste carga o falla; esperar
  respuesta y asociar notificaciones al documento correcto.
- M1 consulta Mailpit directo en 8025 aunque el helper use MAILPIT_API; reutilizar
  la coordenada y fallar cerrado en comprobaciones negativas.

Requieren evidencia adicional:
- Carga de todo el historial de snapshots: mecanismo de crecimiento observado,
  sin RSS/OOM medidos; no se aprueba una optimización de identidad/D5.
- Nombre largo de comparación guardada: truncate está presente, pero falta
  geometría/captura de pérdida de contenido en el SHA servido.
- Virtualización del visor PDF: sin costo medido que justifique cambiar navegación.

Descartes por retorno insuficiente:
- Unificar extractores de errores o acoplamientos internos sin un fallo concreto.
- Retocar paddings, anchos del PDF o pestañas sin desborde demostrado.
- Reabrir header/nav, reanclaje, purgas o consultas que ya fueron corregidos.
- Añadir APM/tracing general sin una necesidad de diagnóstico acotada.

## Entrega

| Dueño | PR | Head de aplicación/tests |
|---|---|---|
| Seguridad | [#67](https://github.com/ProjectAppLabs/versiona_project/pull/67) | `e17da9bb57c2294c1bbea0c4a224ff30ba35ece8` |
| Mantenibilidad | [#69](https://github.com/ProjectAppLabs/versiona_project/pull/69) | `11f74a692ccf27b841da155dcfd096c16bda6153` |
| Observabilidad | [#68](https://github.com/ProjectAppLabs/versiona_project/pull/68) | `179056a47086a7db3fec66c0d806ee9a483ec6fe` |
| Compartido | [#66](https://github.com/ProjectAppLabs/versiona_project/pull/66) | Contrato C3, mapa, reporte y evidencia de esta ronda |

Los diffs contra la base sólo contienen los archivos aprobados. No se cambiaron
dependencias, lockfiles, migraciones ni configuración global. Cada dueño
commiteó su frente; el orquestador publicó los PR y reunió la unión, sin
implementar frentes.

### Fix loop del gate

La primera unión, `fa5a3f7a805022df46dafd5223bbb8a237b529f2`, ejecutó 106 casos
funcionales verdes, pero se rechazó por 29 errores de Ruff en el test de
revisores. El contraste con el blob base halló 30 errores previos; ninguno de
los 29 era nuevo. El CI del PR #67 estaba verde porque Ruff no estaba disponible
y el gate clasifica esa ausencia como warning; el workflow no instala Ruff.

El dueño de Seguridad corrigió únicamente docstrings, imports y la tupla de
parametrización en su test autorizado (`e17da9b`). Se conservaron los node IDs,
aserciones, datos y comportamiento; no se alteraron lógica de aplicación,
baselines, severidad ni configuración. El ajuste pasó el gate con Ruff real y
cero findings. El advisory de ocho aserciones en una transacción se conserva.
Este ajuste desbloquea un check obligatorio del frente, sin abrir una cuarta
causa de mejora.

El intento rechazado se congeló con hashes y el motor canónico lo registró como
REJECTED. La misma QA terminó APROBADA sobre
`86110774cf187f7c108131dc90eb1e41889143dc`, árbol
`1f2ac36cba6f723878d19df71e05f7c06dda4df7`. Se ejecutaron otra vez 68 casos
backend, 26 unitarios y 12 E2E sobre ese SHA; no se atribuyen los resultados de
`fa5a3f7` al commit nuevo.

### Aceptación y evidencia

Las 13 ejecuciones requeridas tienen exit 0: 106 casos, cero skips, fallos o
flaky y tres gates con cero errores de tests o infraestructura. Architect y
Auditor aprobaron el alcance. TSC y ESLint terminaron correctamente; los 16
warnings generales y el advisory de ocho aserciones se conservan.

El orquestador ejecutó `--record-qa` y `--validate-qa` del motor canónico sobre
el SHA limpio exacto: ambos acreditaron `verified=true` en el ledger LOCAL de
Versiona. Las copias saneadas también pasan el validador oficial y sus 63
hashes de exportación coinciden. Esto no actualiza ni verifica el ledger del
toolkit, ni presenta los commits posteriores de documentación como el SHA
ejecutado por QA.

- [Reporte completo de QA](2026-10-10-improvement-round-2-evidence/QA.md).
- [Manifiesto de ejecuciones](2026-10-10-improvement-round-2-evidence/manifest.json).
- [Registro canónico](2026-10-10-improvement-round-2-evidence/record-qa.json) y
  [revalidación](2026-10-10-improvement-round-2-evidence/validate-qa.json).
- [Proveniencia y hashes](2026-10-10-improvement-round-2-evidence/provenance.json)
  y [validación de las copias](2026-10-10-improvement-round-2-evidence/export-validation.json).
- [Intento fa5 rechazado](2026-10-10-improvement-round-2-evidence/rejected-fa5/QA-REJECTED.md),
  [diagnóstico de rutas](2026-10-10-improvement-round-2-evidence/routing-attempt-861/README.md)
  y [arranque frío interrumpido](2026-10-10-improvement-round-2-evidence/cold-start-attempt-861/README.md).

La conversión de los tres JSON Jest preserva nombres, estados y 26 casos; los
nueve JUnit tienen contadores enteros consistentes con sus 94 testcase. Las
erratas de comandos y de la conversión anterior se archivaron por separado,
sin alterar el intento rechazado. El orquestador contrastó los contadores y
resultados de las 13 ejecuciones antes de registrar la aceptación.

Los dos E2E interrumpidos no cuentan como verde. El primero encontró una ruta
Next 404 aunque la API privada respondía 200; se conservó su caché. El segundo
acreditó una navegación RSC de 21,511498 s frente a los 15 s del helper. Su
context L01 se capturó durante la interrupción, sin resultado final. Después
el Next privado dejó de responder: se preservaron trazas y se reinició sólo
ese proceso con el mismo comando y caché, sin cambiar producto ni timeouts.

La preparación final pasó seis HTTP y seis DOM autenticados. La ejecución
aceptada reutilizó esos procesos desde el worktree `8611077`, con CI vacío y
`--forbid-only --workers=1 --retries=0`; el config real controla reuse con CI,
no con E2E_REUSE_SERVER. No se modificaron specs, helpers, configuración fuente,
TTL ni runtime. C3 mostró el contenido real de v2 después de un único 503 y
reintento 200; E1 cubrió sus cinco viewports como regresión.

Los 121 originales regulares se copiaron y verificaron en
`/tmp/versiona-improvement-10102026-ronda2/final-qa-originals-8611077/` antes
del retiro del worktree. Las copias públicas omiten streams, attachments,
propiedades JUnit y entorno de Playwright; conservan resultados y hashes.

### Contrato de integración y cierre

Merge-queue valida la unión final con un PR draft de tren y CI completo,
integra Seguridad → Mantenibilidad → Observabilidad → Compartido y contrasta
el árbol final de master con el del tren verde. El draft nunca se mergea.
El estado MERGED de los cuatro PR y el veredicto final del orquestador acreditan
la integración; el SHA final de master no puede incluirse retrospectivamente en
el mismo commit que lo produce.

Después se retiran sólo los worktrees de esta ronda y sus servicios privados.
Las ocho sesiones anteriores y el checkout de deploy se preservan. El cierre
termina con all-in-base --check-only, sin mutaciones adicionales.

### Riesgos y límites que permanecen

- D5 conserva cobertura parcial: el spec de inbox puede aceptar ausencia antes
  de completar la carga y confundir una notificación ajena con la esperada.
- M1 todavía contiene consultas directas a Mailpit 8025, distintas de la
  coordenada configurada por su helper; las comprobaciones negativas no fallan
  cerrado ante todos los errores HTTP. Ambas causas quedan fuera del cupo.
- El gate de CI permite ausencia de Ruff. Esta ronda exige lint real en QA local
  para sus archivos; no cambia el workflow ni acredita lint del corpus completo.
- No se acredita recuperación frente a caída completa de MySQL ni expiración
  real del worker: los tests de Observabilidad inducen fallos de frontera
  recuperables y un soft timeout, respectivamente.
- E1 ejecuta sus cinco viewports como regresión. No es una certificación visual
  de toda la aplicación ni demuestra el truncado de comparaciones guardadas.
