# Evidencia exportada de QA — segunda ronda

Ejecución sobre el commit exacto `86110774cf187f7c108131dc90eb1e41889143dc`. Los artefactos son resultados reales saneados; no se cambian outcomes, nombres, cantidades ni duraciones. `provenance.json` conserva hashes de los originales y de las copias. El ledger es local de Versiona y no actualiza el toolkit. Los commits posteriores de documentación no se presentan como el SHA ejecutado por esta QA.

# QA delegada — ronda versiona-20261010-ronda2

Veredicto: **APROBADA** sobre `86110774cf187f7c108131dc90eb1e41889143dc`, árbol `1f2ac36cba6f723878d19df71e05f7c06dda4df7`. Validación local de la unión; este informe no acredita CI ni merge.

Causas: Seguridad `I-S-0c3b90d936f0`, visor `I-M-0c0b8831bfb6`, Observabilidad `I-O-42a58784c64c`. El conductor conserva Git y el ledger; QA sólo produjo infraestructura privada y artefactos ignorados. No escribió código, tests, mapas, baseline, memoria ni toolkit.

## Ejecuciones aceptadas

| Capa | Casos ejecutados | Resultado y artefactos |
|---|---:|---|
| Backend / Seguridad | 18 + 15 + 9 = 42 | Tres JUnit reales, todos passed |
| Backend / Observabilidad | 8 + 17 + 1 = 26 | Tres JUnit reales, todos passed |
| Frontend unit / visor | 13 + 7 + 6 = 26 | Tres JSON originales Jest y sus JUnit derivados |
| E2E live / C3 + E1 | 4 + 8 = 12 | JSON real de la ejecución warm-runtime, exit 0 |
| Gate | Tres ejecuciones | Backend, unit y E2E: cero errors/infra_errors/junk nuevo |

**106 casos aprobados, cero skips en ejecuciones requeridas.** Cada tanda tiene como máximo 18 casos; las tandas de backend y unit se organizaron en ciclos de hasta tres comandos. E2E ejecutó sólo dos specs, con un worker, `--forbid-only` y cero retries. No se ejecutó la suite completa.

El manifiesto contiene 13 ejecuciones aceptadas con comandos de fuente real. `command-provenance-crosscheck.json` contrasta las 13 ejecuciones: ocho comandos literales de backend/unit, cuatro comandos con el argv registrado de spawnSync y el comando E2E literal con argv anidado y proceso efectivo. `backend-command-junit-crosscheck.json` contrasta todos los selectores con los 68 testcase de backend. El comando E2E final se copia literalmente de `e2e-warm-runtime/tool-input-final.json`; `command-records.jsonl` registra argv, inicio y final real con exit 0, y `effective-playwright-argv.json` acredita los flags del proceso efectivo. Los campos de salida abreviados del verifier se identifican como resúmenes, no como stdout crudo ni IDs de chunks.

`junit-integrity-verification.json` verifica los nueve JUnit: contadores enteros consistentes con cada testcase/status. `jest-conversion-proof.json` vincula hashes de los tres JSON originales, converter y tres XML; conserva todos los nombres y estados de los 26 casos. No se repitieron pruebas para corregir la conversión.

## Protección observada y revisión estática

Seguridad verificó 404 y cuerpo idéntico para revisor oculto/inexistente, precedencia frente a selección visible inválida, conservación de owner/admin implícitos y de los restantes 400; también nueve regresores de solicitudes. Observabilidad verificó las cuatro fases, excepción real de PDF corrupto y fallo SQL en frontera, privacidad de log, estado FAILED/limpieza, señales separadas de cleanup, éxito y OCR esperado sin ERROR.

Los 26 unitarios del visor verifican respuesta tardía, asociación detalle/archivo al identificador, errores independientes, bloqueo del historial y avisos. C3 live verificó navegar de v1 a v2 con detalle/archivo correctos, retirar v1 ante un único 503, error/reintento visible y recuperación real 200. PDF v2 mostró canvas/página y `8. PROTECCION DE DATOS PERSONALES` dentro del visor; no mostró el marcador exclusivo de v1. E1 verificó las tres vistas de comparación, selección inválida, cinco viewports y navegación por teclado.

Architect y Auditor aprobaron el alcance y conservaron los tests tocados. En el delta de lint fa5→861 sólo cambió el test de Seguridad; nombres, node IDs, aserciones y comportamiento permanecieron equivalentes. No hubo autoría de nuevos guiones fuera del plan ni purga histórica.

## Gate y checks adicionales

La paridad ejecutada fue `--semantic-rules strict --junk-severity=error --external-lint run`; no se usó `--strict`, que convertiría warnings en error y no es el comando de CI. Ruff y ESLint estuvieron disponibles y devolvieron status ok/findings 0. El AST frontend tuvo dependencias instaladas, cero errores de infraestructura y cero archivos include sin resolver.

El gate examinó exactamente seis archivos tocados: dos backend, dos stores unitarios, la página unitaria del visor y C3 E2E. `gate-integrity-verification.json` conserva 2/3/1 archivos por capa. Backend conservó el advisory de ocho aserciones en `test_implicit_org_admin_can_receive_review_assignment` (línea 305). C3 conserva una nota informativa por el actor determinista sembrado. No se cambió baseline ni assertions para eliminar advertencias.

`npx tsc --noEmit` y `npm run lint` devolvieron exit 0. ESLint informó 16 warnings y cero errores; se conserva el advisory de set-state-in-effect documentado. `frontend-static-command-proof.json` acredita argv y retornos de ambos comandos.

## Flows

El auditor no dispone de filtro C3. Se conservó su JSON y se comprobó específicamente `report.flows['c3-history']`: required y satisfied son exactamente `{display,failure,success}`, status covered, junk_only/unvalidated vacíos. `flow-c3-verification.json` más el E2E live acreditan ese flujo. D5 continúa parcial y admin handoff exento; estas limitaciones históricas no se alteraron ni se convirtió el auditor global strict en aceptación imposible.

## Intentos preservados y preparación de E2E

El intento fa5 permanece REJECTED e inmutable bajo `attempt-fa5/`: sus 46 hashes se revalidaron. Su gate real rechazó 29 findings Ruff heredados; CI global antiguo había tenido Ruff unavailable, tratado como warning. Esa diferencia de tooling explica la paridad aparente; el ajuste mínimo del dueño corrigió el lint en SHA861, sin alterar comportamiento.

Las erratas externas `qa-fa5-command-errata.json` y `qa-fa5-junit-conversion-errata.json` no mutan esa evidencia. La primera documenta el selector transcrito incorrectamente y el input real; la segunda, el atributo NaN de XML derivados históricos. El error de selección nuevo exit 4/0 casos y el intento Jest NoTestsFound de fa5 son limitaciones de invocación, nunca resultados verdes. El intento auxiliar de gate con flags/PATH erróneos tampoco es una ejecución aceptada.

En SHA861 el primer E2E se interrumpió exit 130 sin JSON final: cuatro contexts capturaron Next404 en la ruta documento, antes del visor. API versions respondió 200. Se preservó su caché bajo scratch y se recuperó la ruta con el mismo runtime: GET200 y DOM version-item-1 visible. No se atribuyó a producto una ausencia de ruta privada.

La ejecución clean-cache se interrumpió exit 130: el único rojo confirmado agotó el helper upload-dropzone de 15 s. Next trace acredita navegación RSC al proyecto de 21.511498 s (compile 10.826688 s), con toast guardado y formulario anterior. El context L01 se capturó durante interrupción; no tiene resultado final y no se presenta como timeout adicional. La vigencia del JWT durante ese intento se verificó. Ambos intentos sin flush carecen de conteo final canónico y no se contabilizan como casos aceptados.

El primer calentamiento no pasó porque Next privado dejó de responder; control HTTP de 5 s y backend validate 200 se conservaron como diagnóstico, no como fallo probado de producto. Se preservaron trazas/PID y se reinició únicamente Next propio con el mismo `npm run dev -- --port 3121`, conservando caché. Se renovó sesión mediante refresh real privado, sin cambiar TTL. Los seis HTTP y seis DOM autenticados pasaron, incluida página/canvas PDF y comparación, con API200 y cero page errors/404.

La ejecución final reutilizó backend PID305391 y Next PID317245 desde queueWT SHA861. Como la configuración real usa `reuseExistingServer: !process.env.CI`, el wrapper temporal usó CI vacío y `--forbid-only --workers=1 --retries=0`. No cambió fuente/config/runtime/timeouts. `e2e-warm-runtime/live-server-proof.json`, `warm-precondition-proof.json`, `effective-playwright-argv.json` y `playwright-artifact-proof.json` vinculan preparación, procesos y JSON nuevo. Su SHA256 es `a3bf0e23eb4a4ace7ae2002f9af4c4aa6abe337a1972f0978077046b99552e33`; comenzó 18:08:55.894Z, duró 216895.697 ms y tuvo expected12/skipped0/unexpected0/flaky0. El archivo antiguo frontend/e2e-results/results.json no se reutilizó.

## Límites y conservación

Validación dirigida a estas tres causas y sus regresores; no es cobertura exhaustiva ni QA de todo el producto. Q1/Q2 permanecen fuera del cupo. La aceptación E2E local exige preparación de rutas de dev y reutilización explícita; los intentos fríos y abortados quedan visibles como auxiliares.

HEAD y árbol están limpios al inicio/final. Todos los artefactos canónicos son archivos regulares dentro del directorio ignorado de esta ronda. Servicios MySQL3313, Redis6383 y Mailpit8028/1028 siguen privados y sanos; los servidores de aplicación calentados y la evidencia se conservan hasta la señal de cierre del conductor. El conductor registra/valida el manifiesto con su motor local y exporta evidencia saneada; QA no modificó el ledger.
