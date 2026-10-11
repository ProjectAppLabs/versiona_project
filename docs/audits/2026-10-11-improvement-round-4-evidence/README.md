# Evidencia de la cuarta ronda de Versiona

Este índice se congela antes de la QA conjunta. Los resultados finales se
registran en artefactos ignorados del árbol probado, el ledger local y los
cuerpos de los PR. No se commitea evidencia nueva después del SHA servido.

Archivo privado de originales tras el cierre:
`/tmp/versiona-improvement-11102026-ronda4/final-originals/`.
Contiene comandos, códigos de salida, identidad de fuente/servicio, hashes,
reportes originales, intentos fallidos y manifiesto. Mantiene acceso restringido
y no incluye archivos de entorno del deploy. Los artefactos de cada ejecución
son archivos regulares; el manifiesto apunta dentro del worktree probado antes
de su retiro y el archivo conserva su estructura y procedencia.

| Candidato | Fuente implementada | Evidencia propia final |
|---|---|---|
| `I-O-a878b49c51b0` | `190868b3debb459a987e146db01959f344f8b5c3` | 34 casos Django/MySQL y gate estricto; cinco fallos conductuales antes del arreglo. |
| `I-M-2426b181350e` | `6bd9cfd01d5dceb7d86091e5f3f01f72172d4b37` | 20 casos store, 14 panel, ESLint, TypeScript y gate; 15 fallos store y seis panel antes del arreglo. |
| `I-M-3b071b0852e3` | `afd783f04a6adf4d3ef43643ea6a75d6d74c671f` | Gate/ESLint y TypeScript; demos de fallo del oráculo separadas del D5 real. |

La QA combinada ejecuta backend, frontend unit, E2E live y gates sobre un SHA
limpio único. Los fallos esperados de las demos, errores de preparación,
interrupciones y timeouts permanecen separados: ninguno se convierte en verde
ni en crédito de reproducción causal. Tags, autoría y el mapa no prueban
ejecución. Merge-queue exige CI de cada entrega y de la combinación; all-in-base
check-only verifica al final la inclusión squash-aware en la base fresca.
