# Versiona — cuarta ronda de mejora del 2026-10-11

Estado de este documento: alcance implementado y pruebas por frente registradas.
La QA conjunta y la integración se acreditan por sus artefactos originales y
los PR; este documento se congela antes de ejecutar la unión, para que la
evidencia corresponda al commit realmente servido. No certifica seguridad,
rendimiento ni responsividad del proyecto entero.

Base congelada: `master@36e7cafd534b24be82be0581b52d1de8e5d7bcf5`.
El censo inicial no encontró PR abiertos: 33 ramas de trabajo corresponden a
PR mergeados y siete referencias queue son trenes históricos. Se conserva el
checkout de deploy limpio en `492af1e`, sus 32 commits de atraso y las ocho
sesiones anteriores. No se actualiza ni despliega desde esta ronda.

## Decisión

Se revisaron seis frentes sólo en lectura sobre los blobs de la base remota.
Se aprueban como máximo tres causas globales: impacto ALTO, o MEDIO con esfuerzo
BAJO y riesgo BAJO. Cada archivo tiene un dueño. Los agentes implementan y
commitean; el orquestador coordina, registra, verifica y publica, sin implementar
frentes. Configuración, dependencias, lockfiles y migraciones quedan fuera de
los permisos de los implementadores.

| Frente | Estado | Decisión |
|---|---|---|
| Seguridad | MADURO en las rutas revisadas | Sin bypass nuevo confirmado; dependencias sin exposición acreditada. |
| Mantenibilidad | VALE LA PENA | Sellos, validez y plan D5 pertenecen a la versión vigente. |
| Observabilidad | VALE LA PENA | Versión e intención durable de análisis comparten transacción. |
| Rendimiento | NO VALE LA PENA con evidencia disponible | Snapshots, historia de persistencia y PDF necesitan mediciones. |
| Responsividad | NO VALE LA PENA con evidencia disponible | Revisión estática parcial; nombre largo requiere geometría. |
| QA | VALE LA PENA | Corregir falsos positivos del inbox en el E2E D5. |

| ID canónico | Dueño | Impacto | Esfuerzo | Riesgo |
|---|---|---|---|---|
| `I-M-2426b181350e` | Mantenibilidad | ALTO | MEDIO | MEDIO |
| `I-O-a878b49c51b0` | Observabilidad | ALTO | MEDIO | MEDIO |
| `I-M-3b071b0852e3` | QA, mantenimiento del oráculo E2E | MEDIO | BAJO | BAJO |

El motor canónico se usa con ledger LOCAL en artefactos ignorados de Versiona.
QA figura como mantenimiento del oráculo porque el schema no tiene un sexto
frente; la QA conjunta obligatoria no es una causa adicional. La selección de
aplicación se restringe a los frentes aprobados maintainability/observability.
Los adapters históricos de perf/responsive mantienen sus IDs y pendientes: no
se reinterpretan como hallazgos nuevos ni se verifica su historia por inferencia.
Toolkit conserva sus dieciocho archivos sucios preexistentes y no se edita ni
se pushea.

## Contratos y propiedad

**Sellos y D5.** La reproducción con React, Zustand y HTTP diferido mostró sellos
y propuestas A junto a B, y un POST del plan B con decisiones de A. Backend
rechaza esa petición antes de efectos persistentes; el daño acreditado es
presentación incorrecta y bloqueo de confirmación. La solución añade identidad
de versión y generaciones independientes para sellos/plan, protege consultas y
refrescos de mutaciones y filtra el primer render del panel. No cambia backend,
InvalidationReviewCard, reglas D5, permisos ni payloads.

Mantenibilidad posee sealStore, SealsPanel, sus dos archivos unitarios y
`frontend/e2e/app/seals/d5-coordinator-confirmation.spec.ts`. La navegación E2E
usa A → Panel → documento B; desmonta el visor. Una prueba React con stores
reales cubre por separado la instancia conservada. La respuesta A se libera
después de B; defaults, POST y persistencia deben pertenecer a B, y A sigue
pendiente.

**Análisis durable.** Antes del arreglo, complete_upload confirma la versión y
borra staging antes de crear EngineJob. El recuperador sólo recorre jobs, y el
retry encuentra staging ausente o el hash duplicado. Cinco regresores reales
Django/MySQL reprodujeron el fallo sin errores de preparación o teardown;
una ejecución adicional confirmó `(versiones, jobs, contador) = (1, 0, 1)`.

Se descartó envolver toda la subida en otro atomic: eager se ejecutaría bajo
esa transacción y un rollback dejaría objetos finales/thumbnail sin compensación
segura. La alternativa registra versión e intención dentro del atomic/lock
existentes ANTES de put_bytes; mantiene el enqueue/dispatch exterior. Un fallo
inicial no promueve ni borra un objeto preexistente y conserva staging. No se
promete atomicidad entre DB y filesystem ni se cambia el rollback exterior
heredado de onboarding.

Observabilidad posee version_service, engine/tasks y los tests existentes de
analysis_dispatch_failures/version_service. El test de promoción no confirmada
inyecta su fallo después de put_bytes, conservando la garantía de reintento.
Los regresores usan transaction=True, con DB/storage privados: rollback de
versión/job/contador, staging, bytes preexistentes, retry único, broker y commit
exterior, eager y recuperación del análisis original.

**Inbox D5.** El negativo anterior acepta carga/error como vacío y el positivo
admite una invalidación ajena. QA posee exclusivamente
`frontend/e2e/app/seals/d5-selective-invalidation.spec.ts`. Debe registrar GET
antes de navegar, recibir también HTTP fallido, exigir payload y estado final
renderizado, y vincular aviso a sello/documento/v2/link exactos. A puede tener
otros avisos legítimos. Demostraciones controladas de 503, respuesta retenida y
aviso ajeno se conservan separadas del escenario real hasta v3.

## Validación requerida

Reproducciones previas a la corrección: cinco regresores Django/MySQL fallaron
sin errores de setup/teardown; acreditan versión durable sin trabajo, staging
eliminado, promoción de bytes y retry rechazado. La ejecución exacta del store
falló en quince comportamientos y conservó los cinco casos existentes en verde;
no exige campos nuevos como sustituto del fallo. Los intentos interrumpidos,
errores de ruta o descubrimiento de snapshots se conservan por separado y no
cuentan como reproducción ni validación final.

Cada frente conserva rojo y verde originales, comandos literales, salidas reales
y SHA/tree/limpieza. Los tests usan fronteras reales, sin stores de dominio
simulados ni verificaciones estructurales como sustituto del comportamiento.
Máximo veinte casos por comando, tres comandos por ciclo y dos specs E2E;
cero retries o sleeps añadidos y sin ampliar plazos. Nunca suite local completa.

QA conjunta única sobre unión limpia y SHA exacto, con MySQL/Redis/Mailpit/storage
privados y app real del worktree. No se leen .env de deploy ni se ejecuta
manage.py migrate. Ruff, ESLint, TypeScript y gate estricto se ejecutan con
herramientas reales. Los artefactos requeridos serán tipados y verificables;
sin app ejecutada el estado sigue qa-pending.

Resultados propios comprobados sobre cada commit limpio:

| Dueño | Commit fuente | Resultado original final |
|---|---|---|
| Observabilidad | `190868b3debb459a987e146db01959f344f8b5c3` | 34/34 Django/MySQL, sin errores ni skips; Ruff y gate estricto con lint externo exit 0. |
| Mantenibilidad | `6bd9cfd01d5dceb7d86091e5f3f01f72172d4b37` | 20/20 store y 14/14 panel; ESLint, TypeScript y gate estricto exit 0. |
| QA | `afd783f04a6adf4d3ef43643ea6a75d6d74c671f` | TypeScript y gate estricto con ESLint real exit 0; auditoría estática KEEP. El recorrido real se ejecuta en la unión. |

Los timeouts de preparación de Next no ejecutaron casos y no acreditan rojo
causal E2E. Los dos timeouts unitarios de 5000 ms se conservaron; la ejecución
serial posterior pasó sin ampliar límites, añadir retries ni relajar aserciones.
El montaje de React conservado se reprodujo antes del arreglo con seis fallos
conductuales del panel; la navegación live entre documentos lo desmonta.

La preparación de compilación inicial de Next se registra aparte, antes de la
comprobación de arranque de 120 segundos; los plazos y retries de los casos no
cambian. Sólo se sirve una unión por vez. El hasher rápido es exclusivo de los
settings de pruebas privados; no valida seguridad de autenticación. MySQL
privado usa `innodb_flush_log_at_trx_commit=2`: estas pruebas no certifican
durabilidad ante caída de la máquina. Python ejecutado: 3.12.3; Django: 6.0.5.

La evidencia original, el manifiesto final y el ledger local se archivan en
`/tmp/versiona-improvement-11102026-ronda4/final-originals/`, fuera de los
worktrees retirados y con acceso restringido. Las demostraciones controladas
del oráculo se separan de los casos reales; sus fallos esperados no se mezclan
con el manifiesto verde. No se agrega un manifiesto versionado después del SHA
probado. El índice de evidencia explica este corte documental.

## Pendientes, descartes y riesgos

- Mailpit M1: MEDIO/BAJO/BAJO, pendiente por cupo; no descartado por retorno.
- Timing E2E público: timeouts históricos antes del submit y retries verdes;
  falta trace/reproducción del intento fallido para un fix causal.
- CSV: enlace fuera del cliente Bearer; descarga real no reproducida.
- Nombre largo guardado: falta medir pérdida observable de identificación.
- Snapshots/historia/PDF: sin captura SQL/cardinalidad/memoria que justifique
  intervenir. C3 ya está paginado; no se propone paginarlo de nuevo.
- Extracciones cosméticas, paddings y telemetría general: bajo retorno sin un
  fallo o decisión concreta que mejorar.
- Dependencias: se conserva el diagnóstico previo, sin scanner nuevo ni
  certificación de ausencia de exposición.
- Callback de sellado hacia versionStore: recorrido estático, needs-evidence;
  sólo se reabre si se reproduce que B queda bloqueado por una respuesta de A.
- Rollback exterior después de promover un PDF: puede dejar objetos huérfanos
  heredados. No se añade compensación insegura ni se promete atomicidad DB/FS.
- El servicio puede conservar configuración anterior hasta otro despliegue.

## Entrega e integración

Se verifican diez paths exclusivos de los agentes contra master. Compartido
posee reporte, memoria operativa, mapa de flujos y evidencia saneada requerida;
no tiene un frente de aplicación. Cada rama abre PR al primer push, con dueño,
intención, impacto/esfuerzo/riesgo y validación. Merge-queue valida la combinación
con heads congelados; conflictos y fixes se delegan a sus dueños, sin fallback
de implementación del orquestador. Los recursos propios se retiran después
del merge y all-in-base --check-only es la última verificación.

Las calificaciones no acreditan por sí mismas ejecución, CI ni integración.
Los cuerpos de los PR y el reporte final del orquestador conservan los enlaces
y el veredicto efectivo, sin modificar el árbol después de la QA congelada.
