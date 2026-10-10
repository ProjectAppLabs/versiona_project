# Versiona — ronda de mejora del 2026-10-10

Estado: implementación en validación. Ningún resultado pendiente se presenta
como verificado. Base de diagnóstico:
`f0c111980447ab880db4c369eec9f5c29594a94a` (`origin/master`).

## Decisión y alcance

Se diagnosticaron seis frentes en modo de sólo lectura. El criterio fue
aprobar impacto ALTO, o impacto MEDIO con esfuerzo BAJO y riesgo BAJO;
se descartaron preferencias de estilo y riesgos sin un camino demostrado.
El operador limitó la ronda a tres causas globales y autorizó worktrees
externos separados, una rama por frente aprobado y una rama de documentación.
El orquestador integra y verifica; los agentes implementan sus frentes.

| Frente | Estado del diagnóstico | Decisión de esta ronda |
|---|---|---|
| Seguridad | VALE LA PENA | Vínculo Google explícito, recuperación previa y revocación inmediata. |
| Mantenibilidad | NO VALE LA PENA | Sin cambios nuevos en lo revisado. |
| Observabilidad | VALE LA PENA | Diagnóstico del comparador público pendiente por cupo. |
| Rendimiento | VALE LA PENA | Reanclaje de observaciones por lotes acotados. |
| Responsividad | NO VALE LA PENA | Sin cambios nuevos; no se declara validación visual global. |
| QA | VALE LA PENA | Mailpit falla cerrado ante búsqueda, respuesta o purga inválida. |

El motor común se ejecutó sólo con `--refresh --check`: confirmó `proceed`
para las tres causas elegidas. El preview general todavía incluye causas
históricas obsoletas del ledger del toolkit; se contrastaron con el código,
sin aceptarlas como trabajo nuevo. Los previews por alcance aislaron las
causas vigentes. Por instrucción del operador, este registro y la evidencia
viven en Versiona: no se modifica ni se pushea el toolkit. No se atribuye
una actualización ni un estado `verified` al ledger externo.

## Causas aprobadas

| ID del motor | Dueño | Impacto | Esfuerzo | Riesgo |
|---|---|---|---|---|
| `I-S-3b550c956232` | seguridad | ALTO | ALTO | MEDIO |
| `I-P-108f9bbe38dd` | rendimiento | ALTO | MEDIO | MEDIO |
| `I-O-f5de8573e07a` | QA | MEDIO | BAJO | BAJO |

El tercer ID usa `observability/e2e-test-infrastructure` en el motor porque
su taxonomía no tiene frente QA; la autoría y el PR siguen correspondiendo a QA.

**Seguridad.** En la base, `backend/accounts/views/auth.py:288` une cuentas
con `get_or_create(email=...)` y conserva la contraseña preexistente. Un tercero
puede registrar el correo de la víctima, y seguir accediendo después de que
ella use Google y acepte una invitación. La solución identifica Google por
`sub` verificado y único. Un correo ya existente sin vínculo devuelve 409
`google_link_required`, sin sesión ni mutación. Cualquier cuenta histórica sin
`sub` debe recuperar la contraseña por correo; un ticket firmado de 15 minutos,
la sesión vigente, la contraseña actual, una nueva contraseña distinta y TOTP
permiten confirmar el vínculo en Seguridad. No se infiere un vínculo por correo
o por tipo de contraseña. `auth_version` invalida access, refresh y desafíos
anteriores al reset, cambio de contraseña o vínculo; el refresh rotado se guarda
en el cliente. El ticket no autoriza una sesión y no aparece en URLs.

**Rendimiento.** La base (`backend/observations/services.py:179`) hace dos
consultas y una inserción por observación y carga cuerpos completos de secciones
dentro de la transacción de análisis. La solución fija un techo de PK, recorre
lotes de 100 pendientes, proyecta sólo los datos requeridos y crea anclas en
bloque. Conserva la transacción, los tres métodos, snippets, fallback, contadores
e idempotencia. El presupuesto se comprobará con 1, 50 y 201 observaciones;
no se promete una mejora de tiempo de pared sin medirla.

**QA.** En la base (`frontend/e2e/helpers/mailpit.ts:21`), un HTTP fallido
devuelve `[]` y `assertNoEmailFor` pasa. La solución rechaza HTTP fallido y
payload inválido; la purga fallida también rechaza. Sólo una búsqueda correcta
con `messages=[]` certifica ausencia. Se verificó inicialmente con seis casos
Jest sobre `e878f7e429eeaa5c06db242907f4623ab88336af`; la QA final repetirá la
comprobación sobre el commit combinado con artefactos estructurados.

## Propiedad e integración

- `improve/seguridad`: aplicación y pruebas de cuentas y frontend del vínculo;
  mapas de flujos A1/A3. El orquestador posee exclusivamente la migración
  `0004_google_identity_session_version.py`, la selección de autenticación en
  `backend/versiona_project/settings.py` y la selección del launcher privado en
  `frontend/playwright.config.ts`. Estos tres archivos están en el mismo PR que
  la aplicación para conservar su dependencia atómica. Commit inicial del
  orquestador: `88270c7`.
- `improve/rendimiento`: sólo `backend/observations/services.py` y
  `backend/observations/tests/test_reanchor_query_budget.py`.
- `improve/qa`: sólo `frontend/e2e/helpers/mailpit.ts` y
  `frontend/e2e/helpers/__tests__/mailpit.test.ts`.
- `improve/compartido`: planificación, arquitectura, contexto, backlog y este
  reporte; evidencia final saneada cuando esté disponible. No cambia producto,
  dependencias, lockfiles ni el toolkit.

El clon principal permaneció sin edición ni checkout. Los worktrees y ramas
de otras sesiones quedan fuera del alcance. El schema E2E se prepara con el
runner de tests Django en MySQL privado; no se ejecuta `manage.py migrate` desde
un worktree. Los procesos privados usan MySQL 3312, Redis 6382 y Mailpit 8027/1027,
con almacenamiento bajo `/tmp/versiona-improvement-10102026/objects`.

## Verificación y entrega

Pendiente: commit combinado limpio, QA backend/unit/E2E y gate, checks de PR,
tren de merge-queue y all-in-base --check-only. Los resultados iniciales no
sustituyen la verificación final. Los tests locales se ejecutan por archivos
o casos explícitos, en lotes de hasta 20; E2E usa como máximo dos specs,
`CI=1`, puertos privados y cero retries.

PR de QA: [#61](https://github.com/ProjectAppLabs/versiona_project/pull/61).
Otros PR y resultados: pendientes.

## Descartes y condiciones para reabrir

- Extractores de errores duplicados: no se demostró un productor real que
  devuelva el objeto problemático; reabrir con error observable.
- Acoplamiento de `DomainError` entre parser y tareas: sin fallo ni coste de
  mantenimiento medido; no justifica un refactor cosmético.
- Replay directo D5: la única entrada productiva revisada tiene lock y
  checkpoint transaccional; reabrir con duplicado a través de esa entrada.
- Header, navegación pública y controles compactos: las correcciones históricas
  ya están en la base; reabrir ante regresión medida, no repetirlas.
- Footer sin tamaño táctil explícito: sin geometría ni interacción que demuestre
  fricción; reabrir con medición real a 412/835.
- Modal sin límite de altura: no se encontró una acción productiva inaccesible;
  reabrir con modal real y selector afectado, no contenido artificialmente largo.
- APM, tracing y alertas generales: sin necesidad de diagnóstico concreta.

## Pendientes y riesgos abiertos

- Observabilidad `I-O-42a58784c64c`: el comparador público captura una excepción,
  conserva sólo `processing_failed`, elimina los originales y retorna éxito
  a Celery (`backend/public_tools/tasks.py:33-48`). Vale la pena registrar fase
  fija y clase saneada; queda pendiente por el cupo global, no por bajo retorno.
- Si un tercero habilitó TOTP antes de la recuperación, el vínculo conserva ese
  segundo factor. Su recuperación asistida requiere una decisión separada.
- La emisión de códigos de recuperación aún permite quemar el código vigente
  con un intento fallido; riesgo ya aceptado, sin ampliar esta ronda.
- Sellos globales con overrides manuales: falta aclarar el contrato; clasificación
  `needs-evidence`, sin cambio funcional D5 ni declaración de brecha probada.
- Responsividad: diagnóstico estático acotado a layout. No hubo ejecución visual
  de la matriz completa en esta ronda ni certificación de todos los módulos.
- El launcher Google E2E reemplaza sólo el transporte externo oficial tokeninfo;
  los guards exigen la DB y storage privados. Las rutas, validación de claims,
  contraseñas, locks y tokens se ejecutan en la aplicación real.
