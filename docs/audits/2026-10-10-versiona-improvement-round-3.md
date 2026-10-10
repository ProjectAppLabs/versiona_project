# Versiona — tercera ronda de mejora del 2026-10-10

Estado: implementación y QA conjunta verificadas. Integración pendiente de
los CI del tren y del drenaje ordenado de los PR. La evidencia acredita sólo
el alcance seleccionado, no ausencia de deuda en todo el proyecto.

Base común: `2604b8dd44090b26e251ffa78a29b63822ef0c02` (`master` remoto).
El checkout de deploy permanece limpio en `492af1e`; las ocho sesiones
anteriores se conservan. El censo inicial encontró cero PR abiertos y 29 ramas
de trabajo asociadas a PR mergeados; los seis trenes históricos no son unidades.

## Decisión y alcance

Se seleccionaron tres causas globales. Cada archivo tiene un dueño; los agentes
implementan y commitean sus frentes, y el orquestador posee configuración,
registros, publicación, integración y cierre. Sólo se aprueba impacto ALTO o
MEDIO con esfuerzo BAJO y riesgo BAJO. No se añade trabajo para llenar cupos.

| Frente | Estado | Decisión |
|---|---|---|
| Seguridad | VALE LA PENA | Corregir evasión de límites por prefijo XFF. |
| Mantenibilidad | VALE LA PENA | Asociar comparación, diferencias y PDFs a la pareja vigente; PR #73. |
| Observabilidad | VALE LA PENA | Finalizar el seguimiento agotado sin snapshot previo; PR #72. |
| Rendimiento | VALE LA PENA | Reutilización de snapshots pendiente por cupo. |
| Responsividad | NO VALE LA PENA | Sin rotura nueva demostrada en compare; revisión parcial. |
| QA | VALE LA PENA | D5/inbox y Mailpit M1 pendientes por cupo; QA conjunta obligatoria. |

| ID | Dueño | Impacto | Esfuerzo | Riesgo |
|---|---|---|---|---|
| `I-S-2652d50c33dc` | Seguridad + configuración compartida | ALTO | BAJO | BAJO |
| `I-M-a5771227c659` | Mantenibilidad | ALTO | MEDIO | MEDIO |
| `I-O-2e4131e1c3b8` | Observabilidad | MEDIO | BAJO | BAJO |

El motor canónico confirmó `proceed` para las tres causas. El ledger es LOCAL,
bajo artefactos ignorados de Versiona mediante `IMPROVEMENT_LEDGER_DIR`; no se
edita, commitea ni pushea toolkit. Los diagnósticos se hicieron sobre objetos
del SHA base, no sobre el checkout de deploy atrasado. Las reproducciones en
memoria demostraron mecanismos, sin sustituir ejecución de pytest/Jest/E2E.

## Contratos aprobados

**Seguridad.** DRF sin `NUM_PROXIES` usa todo XFF como identidad del throttle.
La configuración nginx instalada de Versiona conserva el prefijo del visitante
y añade su IP: la reproducción admitió todos los prefijos distintos. SSH de
sólo lectura corroboró `/api/` directo al socket Unix de Gunicorn, con un solo
proxy y sin directivas real_ip activas. Copiar `REST_FRAMEWORK` en producción y
fijar `NUM_PROXIES=1` conserva base y desarrollo. Los tests deben consumir la
configuración real, aislando `.env`, filesystem y módulos globales; nunca
imponer en el test el valor corregido. No se probó explotación en producción.

**Comparación.** La respuesta anterior puede reemplazar resultado, diferencia
y PDF de la pareja actual. Se conserva identidad ordenada document/from/to y
generación de petición/consumidor. La guarda opcional de `fetchFileUrl` limita
efectos y avisos 402, manteniendo los retornos independientes de los dos lados
y el comportamiento anterior sin guarda. No se cambia backend, D5 ni UX de
errores genéricos del archivo. Reintento de comparación existente conservado.

**Seguimiento.** Si todas las consultas fallan, el límite de cinco minutos
termina sin callback porque no existe snapshot. El resultado terminal
`failed/timeout` se construye también en ese caso, se guarda y notifica una
vez. No cambian cliente HTTP, intervalos, plazo ni política de consultas.

## Propiedad y validación

- Seguridad: tests existentes de auth throttles y endpoints de comparación
  pública. `settings_prod.py` sólo pertenece al orquestador en compartido.
- Mantenibilidad: compareStore, CompareView, versionStore; tests existentes de
  compareStore, CompareView y versionStore.historyLock; spec E1 existente.
- Observabilidad: jobStore y su test existente.
- Compartido: configuración, contratos de flujos, reporte y evidencia saneada.

Regresores rojos reales preceden los fixes. QA final exige commit limpio con
configuración, aplicación, tests y contrato de flujos. Backend, frontend-unit,
E2E y gate se acreditan con comandos y artefactos tipados del SHA exacto.
Ruff y ESLint deben ejecutarse con herramientas reales. Máximo veinte casos
por comando, tres comandos por ciclo y dos specs por ejecución E2E; cero
retries. MySQL/Redis/Mailpit/storage son privados; sin `.env` de deploy ni
`manage.py migrate`.

La dependencia de Seguridad es explícita: sus regresores aislados permanecen
rojos hasta recibir la configuración compartida. Se valida primero la unión;
merge-queue integra compartido antes de Seguridad. La rama absorbe la nueva
base sin rebase, obtiene CI verde y se recongela el tren si cambian los heads.
Ningún rojo se oculta ni se convierte en entrega por una simulación.

La comparación se prueba con A=v1/v2 retenida, historial al timeline y B=v2/v3
sin recarga; B termina antes de liberar A. Se comprueban contenido PDF real,
diff y guardado persistente de B. `rerender` cubre la instancia conservada que
Next puede desmontar al navegar. C3 y los cinco viewports E1 son regresiones;
el timeout de seguimiento se prueba con reloj controlado y C1/C2 como regresión.
La auditoría de flujos no asigna crédito por declarar outcomes.

## Diferidos, descartes y riesgos

Pendientes por cupo, no por bajo retorno:
- Snapshots: cuatro recorridos/materializaciones frente a dos reutilizables;
  falta captura SQL real antes de afirmar latencia, CPU o RSS.
- D5/inbox: ausencia prematura ante carga/error y notificación ajena; hay
  cobertura backend y otra confirmación D5, pero el inbox automático sigue débil.
- Mailpit M1: consultas directas a 8025 frente a la coordenada del helper y
  negativo que acepta errores HTTP como buzón vacío.

Requieren evidencia adicional:
- Ruff ausente en CI: habilitarlo afecta todo el corpus; falta medir deuda y
  archivos antes de calificar esfuerzo/riesgo. QA local exige lint real.
- Nombre largo de comparación guardada: falta geometría y pérdida observable
  de identificación en el SHA servido.
- Historial completo y virtualización PDF: sin medición representativa de
  consultas/filas/CPU/RSS que justifique intervenir.

Descartes de bajo retorno:
- Mover errores/permisos a core o dividir el motor sin un fallo/coste concreto.
- Retocar paddings, pestañas o PDF sin desborde; reabrir header/nav ya corregidos.
- Añadir APM/tracing general sin una señal necesaria para un fallo concreto.
- Seguimiento con plazo independiente para HTTP que nunca termina:
  MEDIO/MEDIO/MEDIO; fuera de esta corrección mínima.
- Respuestas posteriores a clear: sin consumidor productivo actual de clear.

La integración no despliega: la evasión confirmada seguirá en el servicio
hasta desplegar el código corregido. El cierre de la ronda exige integrar los
PR, conservar evidencia, retirar sólo recursos propios y ejecutar finalmente
`all-in-base --check-only`.


## Historial de validación y decisiones

Los intentos se conservan por separado; ninguno se reetiqueta como aprobado.

- `c494ba8`: el auditor rechazó cinco pruebas nuevas del componente que
  sustituían los stores. El dueño las reescribió con stores reales y fronteras
  HTTP/PDF; `1baa0a5` pasó once casos, TypeScript, ESLint y gate estricto.
- `4c82bd2`: los casos ejecutados pasaron, pero el cierre fue rechazado por
  seis duplicaciones TS2783 del cambio de seguimiento y doce D103 heredados
  en el archivo de comparación pública. El alcance del gate omitía E1 y
  algunas salidas terminales no estaban acreditadas. No se emitió verificación.
- El dueño de seguimiento corrigió únicamente el fallback con
  `current ?? valores_neutrales` (`f9dd2dd`). Seguridad documentó doce funciones
  existentes (`7160cc6`); una comparación AST acreditó comportamiento intacto.
  Son correcciones mínimas para completar los controles obligatorios, no
  mejoras cosméticas elegidas por sí mismas.
- `a34d14c`: 36 casos backend, 62 unitarios y 13 E1/C3 pasaron con salidas
  reales. C1/C2 tuvo once éxitos y un timeout de C2-R02: no existía v2 ni se
  habían enviado sus peticiones de subida. El selector fue un síntoma tardío.
  El manifest rechazado y el contexto original permanecen conservados.
- Una reproducción aislada y el lote diagnóstico posterior pasaron. Sus
  resultados no demuestran la causa del fallo histórico ni lo reemplazan.
  El trace aislado registró interferencia temporal del documento PDF durante
  el tap; falta trace del fallo original. QA Healer concluyó NO-GO a cambios
  de producto/test/config: no hay beneficio causal demostrado. La manifestación
  temporal queda como riesgo conocido, sin atribuirla a la caché.

Preparación separada de los tests: hubo ruta de runner inexistente (127),
selector de calentamiento incorrecto, una invocación unitaria desde la raíz
(254) y ausencia de Ruff en PATH del wrapper oficial. Se conservaron los
intentos; los comandos correctos se ejecutaron con herramientas reales.

Next también produjo un validator de tipos corrupto. La regeneración parcial
permitió TypeScript, pero dejó `/projects` en 404. QA preservó ambas cachés y
recuperó sólo la caché privada completa: seis rutas, PDF/canvas y TypeScript
pasaron con el source intacto. No se acredita que ese defecto de preparación
causara el timeout anterior de C2.

El wrapper oficial devuelve WARN/exit 1 por una advertencia heredada sobre
`timezone.now`; los JSON estrictos tienen cero errores y cero errores de
infraestructura, con Ruff/ESLint reales. No se relajaron reglas ni excepciones.
El stub heredado de `window.prompt` permanece LOW/deferred: idéntico al base,
ningún caso posterior lo consume y no hay reproducción que invalide los once
casos. El rechazo histórico del auditor y la decisión de alcance se conservan.

## Dependencias sin cambios

El audit npm registra 21 paquetes afectados y 69 advisories directos únicos;
lockfile y configuración no cambiaron. Seguridad examinó los dieciséis
HIGH/CRITICAL: condiciones Windows, optimización de imágenes, ImageResponse,
Node/HTTP2 o entradas no confiables no acreditadas para las rutas observadas.
Eso no certifica ausencia de vulnerabilidades ni todas las rutas productivas:
la exposición pendiente requiere evidencia. No hay conteo publicado comparable
para ronda 2; no se afirma que haya aumentado ni que sea idéntico.

## Validación final y evidencia

El verificador y el auditor aprobaron el source limpio
`a34d14c1012387c676da45b9d68ce451dcff78c4`, tree
`187fd6a5d39116deb1cef110ab632363188c7597`. El motor canónico ejecutó
`--record-qa` y `--validate-qa` sobre ese SHA y los artefactos originales:
las tres causas y la ronda quedaron `verified` en el ledger local. No se
modificó el ledger del toolkit. Una invocación de validate sin stdin fue
rechazada por preparación (exit 2); la invocación con el manifest completo
terminó con exit 0.

| Capa | Casos finales | Resultado |
|---|---:|---|
| Backend, dos archivos | 20 + 16 | 36/36, salidas 0 |
| Unitarios, cinco archivos | 20 + 11 + 10 + 8 + 13 | 62/62, salidas 0 |
| E1 + C3, navegador real | 13 | 13/13, salida 0 |
| C1 + C2, navegador real | 12 | 12/12, salida 0 |
| Total | 123 | 123/123, cero skips, flaky o retries |

Los últimos dos lotes se autorizaron después de recuperar la preparación
privada de Next y resolver el diagnóstico NO-GO, sin cambiar source, timeout
ni assertions. Se reutilizó la evidencia de backend/unitarios/gates del mismo
SHA; no se ejecutó una suite local completa. Las doce ejecuciones tipadas
conservan guardas de SHA, tree y limpieza antes y después. Los tres JSON de
calidad tienen cero errores e infraestructura; Ruff/ESLint/TypeScript reales
terminaron en 0. El WARN/exit 1 del wrapper oficial sigue registrado.

La auditoría de flujos mantuvo cuarenta flujos, roles y outcomes: 38 cubiertos,
uno parcial y uno exento, sin specs faltantes ni junk; es lectura estática, no
cuarenta flujos ejecutados. E1 ahora documenta la pareja vigente ante respuestas
viejas; la persistencia comprobada no añade crédito de cobertura E2. Los cinco
anchos E1 (412, 835, 1195, 1440 y 2560) pasaron con PDF real.

La carpeta [de evidencia saneada](2026-10-10-improvement-round-3-evidence/README.md)
incluye el manifest original sin alteración, sus hashes, conteos derivados,
comandos, propiedad y la verificación canónica. Los logs originales, traces,
cachés y estado de navegador se conservan en un archivo privado; no se publican
URLs firmadas ni credenciales. Los intentos rechazados siguen rechazados.

## Solicitudes al orquestador

Aplicadas en compartido, PR #71: `NUM_PROXIES=1` en la configuración de
producción (ALTO/BAJO/BAJO), actualización semántica E1 en el contrato y mapa de
flujos, y reporte/evidencia de la validación obligatoria. No hubo cambios de
dependencias, lockfiles, migraciones ni otras solicitudes globales aprobadas.
Las correcciones mínimas de TypeScript, docstrings y pruebas rechazadas fueron
implementadas por sus dueños, en sus archivos autorizados.

## Riesgos abiertos y cierre

- C2-R02: manifestación intermitente histórica de causa incierta; el lote final
  pasó, pero no se presenta como un arreglo causal. No se debilitaron pruebas.
- El servicio conserva la configuración anterior hasta un despliegue posterior;
  esta ronda integra código y no modifica el checkout ni la base de producción.
- Dependencias npm: exposición pendiente de evidencia; no se declara seguridad
  integral ni se realizan upgrades sin un camino explotable demostrado.
- D5/inbox, Mailpit M1 y snapshots permanecen diferidos; no se consideran hechos.

El tren debe incorporar sólo los heads declarados y sus metadatos finales,
obtener CI verde y luego drenar compartido antes de Seguridad. Los cambios de
metadatos posteriores a QA no se atribuyen al SHA verificado: se validan con
el CI del tren. El cierre final de merge-queue y all-in-base se informa con los
PR y la base remota reales, sin mover el checkout de deploy.
