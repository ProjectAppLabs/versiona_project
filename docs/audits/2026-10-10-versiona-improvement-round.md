# Versiona — ronda de mejora del 2026-10-10

Estado: QA conjunta APPROVED y evidencia exportada verificada. La integración
se realiza después de esta entrega documental mediante merge-queue; los PR
conservan su estado de merge y el cierre al operador confirma all-in-base.
Base de diagnóstico:
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
e idempotencia. Las mediciones iniciales compararon el callable original del
SHA base con el cambio, usando MySQL privado:

| Observaciones | SELECT antes → después | INSERT antes → después |
|---:|---:|---:|
| 1 | 6 → 6 | 1 → 1 |
| 50 | 104 → 6 | 50 → 1 |
| 201 | 406 → 14 | 201 → 3 |

Sobre `f49eeae` pasaron 19 casos del frente, incluidos tres regresores existentes,
sin errores ni omisiones. Estas mediciones no certifican tiempo de pared ni RSS.

**QA.** En la base (`frontend/e2e/helpers/mailpit.ts:21`), un HTTP fallido
devuelve `[]` y `assertNoEmailFor` pasa. La solución rechaza HTTP fallido y
payload inválido; la purga fallida también rechaza. Sólo una búsqueda correcta
con `messages=[]` certifica ausencia. Se verificó inicialmente con seis casos
Jest sobre `009cce8bc6bc99c33680c25f317647d8e5ea36f3`; la QA final repitió
los seis casos sobre el commit combinado, con artefactos estructurados.

## Propiedad e integración

- `improve/seguridad`: aplicación y pruebas de cuentas y frontend del vínculo;
  mapas de flujos A1/A3. El orquestador posee exclusivamente la migración
  `0004_google_identity_session_version.py`, la selección de autenticación en
  `backend/versiona_project/settings.py` y la selección del launcher privado en
  `frontend/playwright.config.ts`. Estos tres archivos están en el mismo PR que
  la aplicación para conservar su dependencia atómica. Commit inicial del
  orquestador: `88270c7`. Durante la verificación, Seguridad confirmó que el nuevo
  recorrido Google no podía correr en CI: faltaban el launcher y los client IDs,
  y su coordenada no cumplía los guards. Se aprobó la solicitud mínima para
  `.github/workflows/ci.yml`, exclusivamente el job `frontend-e2e-tests`, en el
  mismo PR (`68ae17d`). Usa DB `versiona_e2e_ci` en 3312, storage bajo `/tmp` y
  client IDs sintéticos; mantiene todos los guards y no omite el nuevo recorrido.
  YAML y coordenadas fueron comprobados. Impacto MEDIO, esfuerzo BAJO, riesgo
  BAJO: dependencia necesaria de validación, no una cuarta causa.
- `improve/rendimiento`: sólo `backend/observations/services.py` y
  `backend/observations/tests/test_reanchor_query_budget.py`.
- `improve/qa`: sólo `frontend/e2e/helpers/mailpit.ts` y
  `frontend/__tests__/helpers/mailpit.test.ts`. El test se reubicó después
  de confirmar que el testDir de Playwright cargaba el archivo unitario de Jest
  y abortaba la colección. La nueva ubicación permite ambos runners sin cambiar
  configuración global. Un segundo traslado puro salió de `e2e-helpers`: el
  engine unitario excluye cualquier ruta que contenga `e2e`, por lo que no
  descubría el test. Seis casos y `playwright --list` volvieron a pasar;
  la revisión final exigirá que el gate escanee realmente ese archivo.
- `improve/compartido`: planificación, arquitectura, contexto, backlog y este
  reporte; evidencia final saneada cuando esté disponible. No cambia producto,
  dependencias, lockfiles ni el toolkit.

El clon principal permaneció sin edición ni checkout. Los worktrees y ramas
de otras sesiones quedan fuera del alcance. El schema E2E se prepara con el
runner de tests Django en MySQL privado; no se ejecuta `manage.py migrate` desde
un worktree. Los procesos privados usan MySQL 3312, Redis 6382 y Mailpit 8027/1027,
con almacenamiento bajo `/tmp/versiona-improvement-10102026/objects`.

## Verificación y entrega

QA aprobó el commit limpio `bdd1994e938f7f0e3138f21b699bdd8aad4de8d8`:
54 casos backend, 80 unitarios y 13 E2E, **147 casos candidatos distintos**, sin
fallos ni omisiones. Se ejecutaron por archivos o casos explícitos, en lotes
de hasta 20. E2E usó dos specs, `CI=1`, puertos privados, servidores nuevos y
cero retries; duró 169,54 segundos, sin flaky ni errores del runner.

Los tres gates strict con lint externo pasaron sin errores ni fallos de
infraestructura: backend 10 archivos, score 96, 18 warnings; unit 9 archivos,
score 99, 5 warnings; E2E 2 archivos, score 95, cero warnings. Los advisories
quedan registrados sin añadir refactors. El Auditor cerró los falsos verdes
y clasificó KEEP los tres candidatos. La auditoría **estática** de flujos
encontró 40: 38 cubiertos, D5 parcial y admin handoff exento; cero ausentes.
No acredita ejecución de los 40 flujos. AuthStore ejecutó 15/24 casos únicos
mediante filtros auxiliares, con omisiones declaradas y fuera del manifiesto.

El verificador oficial readonly aceptó el manifiesto original y la copia
saneada: `valid=true`, asociación exacta de ronda, commit y candidatos. Evidencia
durable en [QA.md](2026-10-10-improvement-evidence/QA.md), con manifiesto,
registro local, resultados reales y hashes de origen/exportación. No se versionan
stdout, traces, cookies, secretos ni logs crudos; el ledger externo no se modifica.

Los PR de aplicación tienen CI remoto verde en sus heads definitivos:
[Seguridad](https://github.com/ProjectAppLabs/versiona_project/actions/runs/38062765903),
[Rendimiento](https://github.com/ProjectAppLabs/versiona_project/actions/runs/38061542178) y
[QA](https://github.com/ProjectAppLabs/versiona_project/actions/runs/38061753687).
El cierre añade sólo documentación y evidencia. Merge-queue valida también esa
combinación mediante su tren; all-in-base --check-only confirma la integración
sin tocar el checkout de deploy.

| Entrega | PR | Commit del frente | Estado al publicar esta evidencia |
|---|---|---|---|
| Seguridad | [#64](https://github.com/ProjectAppLabs/versiona_project/pull/64) | `b62fd88` | CI verde, QA APPROVED; tree idéntico a `a719bb8`. |
| Rendimiento | [#63](https://github.com/ProjectAppLabs/versiona_project/pull/63) | `9ca84ef` | CI verde, 19 casos finales y QA APPROVED. |
| QA | [#61](https://github.com/ProjectAppLabs/versiona_project/pull/61) | `3ce16e4` | CI verde, seis casos finales y QA APPROVED. |
| Compartido | [#62](https://github.com/ProjectAppLabs/versiona_project/pull/62) | Commit de esta entrega documental | Contrato, decisiones y evidencia verificada. |

La combinación preliminar `519e2ad9285fe421f266eb497c803965a9f86499` quedó
REJECTED: el Auditor encontró precondiciones débiles y el gate bloqueó los tests
tocados. Después de las correcciones de sus dueños, la aplicación y los tests
se combinaron sin conflictos en el commit limpio
`5e3ba0ac6c0fd8ee453edefb321c9d6d3a8080e2`. Una revisión posterior señaló un `if`
que ya estaba eliminado: la lectura directa confirmó que no existía. El traslado
adicional de las assertions a un helper quedó descartado por bajo retorno y
su dueño lo revirtió. La combinación final limpia es
`bdd1994e938f7f0e3138f21b699bdd8aad4de8d8`, con tree idéntico a `5e3ba0a`.
La QA final se ejecutó contra este SHA; el cierre posterior sólo añade documentación
y evidencia. El diff contra
la base contiene exactamente 47 archivos de Seguridad (cuatro globales del
orquestador), dos de Rendimiento y dos de QA; no hay archivos fuera del alcance
ni propietarios superpuestos. Compartido contiene sus seis documentos y la
evidencia saneada de esta ronda.

### Incidencias de validación inicial

- El test unitario de Mailpit ubicado bajo `e2e/` fue recogido por Playwright y
  abortó la colección. El agente lo trasladó a `frontend/__tests__/e2e-helpers/`;
  seis casos y la colección Playwright volvieron a pasar, sin cambiar config.
- Seguridad tuvo dos fallos E2E: sincronización de navegación y duplicación del
  widget Google simulado. El agente corrigió ambos dentro de sus archivos.
  El A3 pasó en `06e3bb6`; precede al ajuste final de continuidad y por eso
  se repiten ambos specs sobre el SHA combinado.
- Hubo dos timeouts unitarios de cinco segundos, revalidados sin aumentar el
  límite. Un lote previo ejecutó 21 casos en vez del máximo de 20: desviación
  explícita. La QA conjunta conserva el límite y registra sus propias
  ejecuciones, sin sumar revalidaciones como casos nuevos ni ocultar omisiones.
- El primer E2E combinado en `519e2ad` salió con error antes de ejecutar casos:
  expiró el arranque del servidor a los 180 segundos. No prueba una regresión
  conductual; se conserva como intento fallido y no como evidencia candidata.
- El Auditor detectó tres precondiciones débiles en las pruebas de seguridad:
  el caso anti-replay no disponía de refresh, el access previo al vínculo podía
  estar ausente y la conservación TOTP sólo exigía presencia. Se autorizó al
  mismo dueño reforzar esas comprobaciones sin cambiar la aplicación.
- El gate estricto con linter externo encontró 65 errores en los tests tocados.
  El mismo engine sobre `f0c1119` confirmó 23 errores y seis warnings previos:
  el delta es 40 errores nuevos de seguridad y dos de rendimiento. El cierre
  mínimo de docstrings, imports y tuplas se autorizó exclusivamente en esos
  tests, incluidos los 23 errores heredados que impedían el hardgate. No se
  debilita el linter ni se toma esta necesidad como un frente de limpieza general.
- El intento independiente de rendimiento tras corregir las dos tuplas produjo
  19 errores de preparación: su schema privado había recibido la migración
  `auth_version` de la combinación, ausente en la rama independiente. El agente
  conservó el reporte fallido y comprobó la colección de los 19 casos; la prueba
  conductual final debe correr en la combinación con su schema correspondiente.
- El CI inicial de Seguridad falló en dos pruebas de onboarding Google: su
  fixture ya simulaba tokeninfo, pero omitía `sub`, `iss` y `exp`. Se autorizó al
  dueño adaptar sólo `backend/orgs/tests/test_onboarding.py` a claims completos
  y afirmar la admisión antes de consultar la cuenta; no se reintroduce bypass.
  Un primer intento del dueño esperaba 201 en vez del 200 real; corregida esa
  expectativa, pasaron los cuatro casos distintos y el gate del archivo quedó
  sin incidencias (`a719bb8`).
- El preflight marcó el mapa como stale porque su glob `backend/**/views/*.py`
  incluye también `backend/accounts/tests/views/*.py`. Sólo señaló tests
  modificados, sin rutas ni vistas productivas cambiadas. Architect revisó los
  flujos A1/A3 reales y el mapa; no se despachó Analyst ni se modificó el motor
  del toolkit para este falso positivo. El gate y la auditoría de cobertura de
  flujos siguen siendo obligatorios.
- El primer comando E2E final recibió del orquestador dos nombres de variables
  incorrectos (`EXPECTED_DB`/`EXPECTED_ROOT`). El launcher privado salió antes
  de ejecutar casos. Se conserva ese intento; el comando se corrigió a
  `E2E_GOOGLE_HARNESS_DB_NAME` y `E2E_GOOGLE_HARNESS_STORAGE_ROOT`, con los mismos
  valores privados. El job CI ya usaba esos nombres correctos. No se modificó
  código, guards, timeouts ni retries para resolver el error de coordinación.

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
- Trasladar las assertions de configuración Mailpit en A3: el `if` ya estaba
  eliminado y no había falso verde demostrado; no justifica otro ajuste.

## Pendientes y riesgos abiertos

- Observabilidad `I-O-42a58784c64c`: el comparador público captura una excepción,
  conserva sólo `processing_failed`, elimina los originales y retorna éxito
  a Celery (`backend/public_tools/tasks.py:33-48`). Vale la pena registrar fase
  fija y clase saneada; queda pendiente por el cupo global, no por bajo retorno.
- Si un tercero habilitó TOTP antes de la recuperación, el vínculo conserva ese
  segundo factor. Su recuperación asistida requiere una decisión separada.
- La cobertura E2E histórica de D5 sigue parcial en display/failure. El reanclaje
  aprobado pasó sus regresores backend; esta ronda no certifica todo D5 en UI.
- La emisión de códigos de recuperación aún permite quemar el código vigente
  con un intento fallido; riesgo ya aceptado, sin ampliar esta ronda.
- Sellos globales con overrides manuales: falta aclarar el contrato; clasificación
  `needs-evidence`, sin cambio funcional D5 ni declaración de brecha probada.
- Responsividad: diagnóstico estático acotado a layout. No hubo ejecución visual
  de la matriz completa en esta ronda ni certificación de todos los módulos.
- El launcher Google E2E reemplaza sólo el transporte externo oficial tokeninfo;
  los guards exigen la DB y storage privados. Las rutas, validación de claims,
  contraseñas, locks y tokens se ejecutan en la aplicación real.
