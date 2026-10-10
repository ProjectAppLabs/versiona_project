# Versiona — tercera ronda de mejora del 2026-10-10

Estado: implementación y QA conjunta pendientes. Este reporte no acredita
resultados de ejecución ni integración hasta que sus evidencias se incorporen.

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
| Mantenibilidad | VALE LA PENA | Asociar comparación, diferencias y PDFs a la pareja vigente. |
| Observabilidad | VALE LA PENA | Finalizar el seguimiento agotado sin snapshot previo. |
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
