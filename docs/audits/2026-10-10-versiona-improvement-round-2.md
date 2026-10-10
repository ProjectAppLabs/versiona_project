# Versiona — segunda ronda de mejora del 2026-10-10

Estado: implementación y verificación en curso. Este documento no acredita QA,
CI verde ni integración hasta que se incorpore su evidencia final.

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

El motor canónico se usa sólo en preview y validación readonly. Los previews
por alcance confirman `proceed` de Seguridad y Mantenibilidad. Observabilidad
reutiliza el ID previo y requiere revalidar el contexto obsoleto con el código
y las pruebas de esta ronda. El preview general contiene causas históricas del
ledger que ya no corresponden al código: no se adoptan como trabajo nuevo.
El toolkit no se edita ni se pushea; decisiones y evidencia se entregan en
Versiona y no se atribuye un estado `verified` a su ledger externo.

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

Pendiente: evidencia roja/verde, QA conjunta, commits y PR de cada dueño,
CI, tren merge-queue, retiro de worktrees propios y all-in-base --check-only.
El reporte final incluirá IDs de PR, SHA probado, artefactos y límites reales.
