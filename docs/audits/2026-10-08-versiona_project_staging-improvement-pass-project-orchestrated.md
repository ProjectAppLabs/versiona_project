# Ronda coordinada de mejora — Versiona

Fecha UTC: 2026-10-08. Base de partida: `master@5b373efa54b42503457e8c8a1adda622f0a328b2`.
Las entregas anteriores #37–#39 ya estaban integradas; no se implementaron otra vez.

## Diagnóstico y selección

| Frente | Diagnóstico actual | Causa atendida |
|---|---|---|
| Seguridad | CON BRECHAS: consumo de respaldo desde instancias antiguas y recuperación con escrituras separadas. | `I-S-f729cb68b016` |
| Mantenibilidad | CON BRECHAS: el cuerpo real del polling permite que una respuesta A antigua sobrescriba una comparación B posterior. | `I-M-4a835d9294ef` |
| Observabilidad | CON BRECHAS: los errores de borrado se silencian y la purga pierde la referencia al PDF. | `I-O-d1612d51180a` |
| Rendimiento | CON BRECHAS: relaciones de papelera consultadas por elemento; 9 consultas con tres filas, 105 con 75. | `I-P-14e4122069ea` |
| Responsividad | CON BRECHAS: navegación autenticada sin menú compacto/vertical, pública desde md y objetivos nominales de 36 px. | `I-R-5689a0c7c4a0`, `I-R-4aa36c0d5fa1` |
| QA | CON BRECHAS: concurrencia, cancelación y eliminación fallida necesitaban casos conductuales; el CI inicial quedó incompleto por falta de runners. | Cierre conjunto de los cambios |

No se identificó un frente global MADURO. La revisión aporta mecanismos concretos
para intervenir; no certifica el resto del proyecto. El operador eligió atender
todos los frentes en lugar del cupo normal de tres causas. Se preservan IDs y el
motor canónico; las asociaciones de QA se registran en grupos de hasta tres.

## Propiedad y resultado funcional

- **v1 — `improve/security`:** bloqueo y relectura del usuario al consumir un
  respaldo; contraseña y código de recuperación en una transacción. Conserva
  el código ante contraseña rechazada o fallo de escritura. El comparador
  cancela transporte y timer al cambiar de página/resetear, y sólo la carga
  vigente puede publicar resultados. Interfaz interna: `load(id, signal?)`.
- **v2 — `improve/observability`:** archivo ausente sigue siendo éxito
  idempotente. Los fallos reales llegan al caller, la limpieza intenta ambos
  slots y conserva la fila para reintentar. El barrido avanza aunque una fila
  falle, sin cargar el JSON de resultados. La limpieza post-promoción de uploads
  no impide analizar una versión ya creada; los logs contienen fase/clase.
- **v3 — `improve/responsive`:** un único nav por header, desplegable antes de
  lg y escritorio desde lg; mismos destinos, orden y permisos. Objetivos de
  44 px, cierre exterior/Escape y devolución de foco. Tema, idioma y campana
  mantienen su comportamiento.
- **v0 — `improve/performance`:** precarga de autor y contexto de papelera,
  conservando respuesta y permisos. También posee registro de flujos,
  documentación, configuración y coordinación de QA. `E2E_PYTHON_BIN` permite
  usar un venv externo sin enlaces; el entorno backend omite valores undefined
  para cumplir el tipo de Playwright.

Las sesiones sólo escriben sus archivos. v2 recibió una ampliación explícita
para el caller de limpieza post-promoción; v3 para adaptar únicamente la entrada
al panel en B2-R01 después del nuevo menú compacto. No se compartió su propiedad
con otra sesión. La variante `improve/<frente>` fue solicitada por el operador.

## Entregas

| Sesión | Frentes | PR | Base |
|---|---|---|---|
| v1 | Seguridad y mantenibilidad del comparador | [#42](https://github.com/ProjectAppLabs/versiona_project/pull/42) | `master` |
| v2 | Observabilidad y recuperación de limpieza | [#41](https://github.com/ProjectAppLabs/versiona_project/pull/41) | `master` |
| v3 | Responsividad pública y autenticada | [#43](https://github.com/ProjectAppLabs/versiona_project/pull/43) | `master` |
| v0 | Rendimiento, archivos compartidos y cierre QA | [#44](https://github.com/ProjectAppLabs/versiona_project/pull/44) | `master` |

## Pruebas y evidencia

| Dueño | Evidencia conductual |
|---|---|
| v1 | 24 pytest locales: siete nuevos y 17 de regresión; dos conexiones MySQL reales, instancias obsoletas y rollback después de SQL. 20 Jest y tres E2E: dos respuestas tardías y un fallo vigente. |
| v2 | 49 pytest en lotes de 17, 16 y 16: errores reales del filesystem, recuperación, progreso con 101 filas, OCR y post-promoción. |
| v3 | 24 Jest de componentes y permisos; 35 casos de la matriz E2E pública/autenticada sobre las cinco dimensiones obligatorias. En el SHA `713c835` del PR pasan esos 35 y tres casos de regresión B2 sin retry; 26 mediciones verifican la geometría. |
| v0 | Tres nuevos pytest de presupuesto, metadatos/orden y descendientes; permisos se verifican con la matriz ya existente de `test_project_endpoints.py`, sin duplicar casos. Gate estricto, TypeScript y lint del harness. |

El test de presupuesto falló antes de la corrección: `105 != 9`. Después debe
mantener consultas constantes y un máximo de seis para tres o 75 elementos;
los valores exactos del JUnit son cinco consultas para ambos tamaños. No se
extrapolaron latencia ni RAM del entorno de desarrollo al VPS. El perfil real
de referencia declara 1 vCPU, CPUQuota 40 % y MemoryMax 300M.

Entorno local: MySQL 8.0.46 privado en puerto 3309, schemas separados por sesión,
Redis privado 6383, almacenamiento de pytest y puertos UI/API propios. Los
schemas se prepararon mediante pytest, sin ejecutar `manage.py migrate` en
worktrees ni usar la base del servicio. Las ejecuciones locales se limitaron a
archivos/casos concretos, máximo 20 por lote y dos archivos E2E por ejecución.

Los artefactos locales quedan gitignored en los worktrees respectivos. La
evidencia remota y el veredicto de cada SHA se consultan en sus PR; el tren de
integración valida la combinación antes de integrar los PR originales.

QA revisó las pruebas contra el código real. Se retiraron dos casos nuevos de
permisos que duplicaban la matriz existente y se congeló el reloj de la prueba
que crea comparaciones vencidas. El gate local ejecuta Ruff real; detectó y
corrigió docstrings/imports que el runner remoto sin Ruff no había comprobado.
Las advertencias de cantidad de aserciones se conservan porque cada prueba
verifica un único contrato atómico de recuperación, no casos independientes.

## QA conjunta verificada

El QA Verifier aprobó el commit limpio
`4d067815589b348c3bfd3deba6319ee833ab79f0`: **29 backend, 44 unitarios y 41 E2E**
(114 casos), sin skips, fallos ni retries. El gate estricto obtuvo **98/100**,
cero errores y seis advertencias KEEP del Auditor. Se ejecutaron Ruff y ESLint
reales; no se elevó el baseline ni se desactivaron reglas.

La [evidencia publicada](2026-10-08-improvement-evidence/QA.md) conserva resultados,
comandos y hashes. El [snapshot del ledger](2026-10-08-improvement-evidence/ledger-snapshot.yml)
fue producido por el motor canónico: los seis candidatos figuran `verified` en
dos asociaciones de hasta tres IDs, con el mismo commit y cierre QA.

Los E2E se ejecutaron con `localhost`; el ensayo anterior con 127.0.0.1 produjo
una conexión de desarrollo inválida y no se usa como prueba aprobada. v1 aisló
la diferencia de hidratación y confirmó los tres casos de comparación sin
cambiar producto, spec ni timeouts para ese fallo.

El empaquetado de evidencia es posterior a ese commit probado y sólo modifica
documentación/artefactos. El tren remoto verifica el árbol combinado completo;
los PR originales mantienen su atribución y la rama draft sólo valida.

## Flujos y límites

El registro 2.4.0 incorpora `layout-public-navigation`,
`layout-authenticated-navigation` y `public-compare-lifecycle`. La cobertura se
acredita por interacción y outcome, no por presencia de una página. Los E2E
deben servir el contenido probado; autoría y capturas por sí solas no cuentan.

Pendientes para otra ronda: revocación de acceso a la bandeja de revisiones,
mutaciones en proyectos archivados, concurrencia/replay de decisiones D5,
listados/historias sin cota y otras superficies responsive sin revisar. La
limpieza fallida de uploads temporales mantiene el objeto y deja diagnóstico,
pero aún no existe un barrido propio de esos residuales.

El control remoto actual de calidad no instala Ruff y puede omitir esa parte
del lint. Esta ronda lo ejecuta localmente sobre las pruebas modificadas; alinear
el runner y auditar el corpus anterior queda pendiente para la próxima ronda.

El remoto del toolkit canónico está archivado en GitHub y no admite pushes.
La evidencia de esta ronda se conserva aquí para disponer de un destino
publicable; las decisiones siguen producidas por el motor canónico, sin
modificar su política. El clon desplegado permanece intacto. No hubo deploy.
