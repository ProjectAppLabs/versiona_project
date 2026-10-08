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
para el caller de limpieza post-promoción; no se compartió su propiedad con
otra sesión. La variante `improve/<frente>` fue solicitada por el operador.

## Pruebas y evidencia

| Dueño | Evidencia conductual |
|---|---|
| v1 | 24 pytest locales: siete nuevos y 17 de regresión; dos conexiones MySQL reales, instancias obsoletas y rollback después de SQL. 20 Jest y dos E2E del ciclo de vida. |
| v2 | 49 pytest en lotes de 17, 16 y 16: errores reales del filesystem, recuperación, progreso con 101 filas, OCR y post-promoción. |
| v3 | 24 Jest de componentes y permisos; 35 casos de la matriz E2E pública/autenticada sobre las cinco dimensiones obligatorias. Su ejecución final corresponde al SHA del PR. |
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

El remoto del toolkit canónico está archivado en GitHub y no admite pushes.
La evidencia de esta ronda se conserva aquí para disponer de un destino
publicable; las decisiones siguen producidas por el motor canónico, sin
modificar su política. El clon desplegado permanece intacto. No hubo deploy.
