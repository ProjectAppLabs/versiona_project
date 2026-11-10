---
name: "vpn-connect"
description: "Revisa la conexión de ESTE host a la VPN del fleet y verifica el alcance real con status, ping y una sonda SSH para detectar el check mode. Si falta conectar o autorizar, guía al operador para que corra el up del runbook de canales en su propia terminal y abra el enlace en su navegador, sin pegarlo en ningún lado. La sesión no ejecuta up ni busca o muestra enlaces de login. Después vuelve a verificar: un nodo conectado con autorización SSH pendiente no es verde. Complementa a $bootstrap-vpn-fleet (onboarding/audit/registry)."
---

# VPN Connect

Revisa **el host actual** y verifica que el fleet sea alcanzable. Si hace falta
conectar o autorizar, el operador corre el `up` indicado en el runbook de canales (el README junto a `config/*/expected-nodes.yml`)
en su propia terminal y abre el enlace allí, sin pegarlo en ningún lado.
La sesión no ejecuta `up`, no busca enlaces ni los muestra; vuelve a verificar
después. Es el complemento operativo de $bootstrap-vpn-fleet.

> **⚠️ Cómo invocar**:
> - `$vpn-connect` → revisa este host, guía la conexión manual si falta y
>   verifica después el alcance al fleet.
> - `$vpn-connect --check` → diagnóstico read-only (Phases 0, 3 y 4), no
>   conecta ni re-autentica, pero SÍ sondea el *check mode*.
> - `$vpn-connect --no-ssh-probe` → sólo el estado local del nodo; el
>   alcance al fleet queda sin verificar (y se dice en el reporte).
> - Opera **siempre sobre el host donde corre la sesión** (identificado por
>   `hostname -s`). No corre trabajo en otros VPS; el único contacto con un peer
>   es el probe read-only de Phase 4 (`bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ssh <peer> true`).

## Cómo invocar este skill

Gating ($output-protocol §4): (1) flag explícito (`--check`) → directo, sin menú;
(2) intención clara por contexto ("conectá este host al tailnet") → proponer el comando
en una línea y esperar confirmación; (3) sin args → UNA AskUserQuestion (Q1); (4) nunca
en fleet/headless/cron — el OAuth exige al operador en el browser.

**Q1 — Modo** (`multiSelect: false`):

| label | description | preview |
|---|---|---|
| Revisar y guiar este host (Recommended) | revisa el estado, guía al operador a la autorización en su terminal si falta y verifica después; no corre up ni muestra enlaces | `$vpn-connect` |
| --check | verificar sin mutar nada: estado local + probe del *check mode* | `$vpn-connect --check` |

**Qué NO se pregunta:** el `--hostname` del `up` manual lo determina el host
identificado en Phase 0, según el runbook de canales. **Tampoco se pregunta si sondear el fleet**: el probe es el
dato que motiva la skill y corre siempre — `--no-ssh-probe` existe para offline y se
tipea, no se ofrece.

## Cuándo usarla

- Workstation nueva o VPS recién provisionado que todavía no está en el tailnet.
- Tras un `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh down` / logout / expiración de key: reconectar rápido.
- Cuando necesitás guiar la autorización en tu terminal y comprobar después
  que el fleet quedó alcanzable, sin compartir el enlace de login.

Para **auditar** el tailnet, **registrar** el nodo en `expected-nodes.yml`, o el
onboarding completo bimodal, usá $bootstrap-vpn-fleet / $init-fleet.

## Diferencia con $bootstrap-vpn-fleet

| Aspecto | vpn-connect (este) | bootstrap-vpn-fleet |
|---|---|---|
| Corre el `up` | No; lo corre el operador en su terminal según el runbook de canales | No; remite a este modo |
| Busca o muestra el link en la respuesta | No | No |
| Espera autorización manual + verifica | **Sí** | Remite a este modo para auth |
| Toca el registry / admin console | No | Sí (`--add-self`, `--audit`) |
| Alcance | Sólo el host local | Bimodal dev/VPS + fleet |

## Procedimiento (lo que Claude ejecuta)

### Phase 0 — Identificar host + preflight (read-only)

1. `hostname -s` → mapear a alias: `srv571894`→vps-projectapp-staging,
   `srv1681495`→vps-projectapp-prod, `srv614758`→vps-gym. Dev machine si
   `is_dev_machine` (helper de `scripts/lib/bootstrap-common.sh`).
2. Determinar los flags del `up` manual según el runbook de canales:
   **dev** → `--ssh`; **VPS** → `--ssh --hostname=<hostname del host>`.
   La sesión no ejecuta ese comando.
3. Preflight:
   - Instalación y demonio de la VPN: `bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --check`
   - **Ya conectado?** `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status >/dev/null 2>&1`
4. **Corto-circuito idempotente**: si ya está conectado, **saltar Phases 1-2**
   (no re-autentica el nodo) y **seguir en Phases 3-4** — verificación local y
   probe de sesión SSH.
   ⚠️ **NO terminar acá.** Cortar en este punto es lo que producía el falso
   «🟢 ya conectado» que después se frenaba pidiendo el link en la primera
   operación cross-VPS: `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status` sólo prueba que el NODO está en el
   tailnet, nunca que la sesión SSH esté autorizada (*check mode*).
   Con `--check` vale lo mismo: se saltan las fases mutantes, pero Phase 4 corre
   igual — es read-only y es el dato que el operador vino a buscar.

### Phase 1 — Install + enable (sólo si falta)

Sin `--check`, si falta el cliente o el demonio de la VPN, usá
`bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --apply`, **nunca con sudo**.
Con `--check`, reportá lo que falta sin instalar ni habilitar nada.

### Phase 2 — Conexión y autorización en la terminal del operador

Si hace falta conectar o autorizar, pedile al operador que corra el `up` indicado en
el runbook de canales (el README junto a `config/*/expected-nodes.yml`)
en su propia terminal, con los flags de Phase 0. El operador abre el enlace en
su navegador, sin pegarlo en el chat, en Slack ni en ningún otro lado.
La sesión no corre `up`, no lo lanza en background, no captura su salida ni
busca o muestra la URL. Esperá a que el operador confirme que terminó.
Con `--check`, sólo informá la autorización pendiente y esta acción manual.

### Phase 3 — Verificar después de la autorización

1. Si hubo autorización manual, volvé a verificar tras la confirmación del
   operador. Si el nodo ya estaba conectado, verificá directamente. No infieras
   el cierre de una tarea en background, porque la sesión no lanzó ninguna.
2. Verificar (triada de `~/webapps/vps-ops-toolkit/scripts/vpn/fleet-check.sh`):
   - `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status` sale 0
   - `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ip -4 | head -1` devuelve una IP `100.x`
   - nodo: `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status --json | jq -r '.Self.DNSName // "" | split(".")[0]'`
   - (VPS) ssh cap habilitado: `bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --check` lo lee
     de las capacidades del nodo y reporta «SSH server activo en este VPS»; esta
     skill no escribe el identificador del proveedor.
3. Next steps a sugerir:
   - Si el nodo **no** está en `config/*/expected-nodes.yml`:
     `$bootstrap-vpn-fleet --add-self` para registrarlo.
   - (VPS) recordatorio manual: *Disable key expiry* en la consola de
     administración de la VPN (su URL está en el runbook de canales).

### Phase 4 — Probe de sesión SSH (*check mode*) — read-only, SIEMPRE

**Por qué existe (no la saltes):** «nodo conectado» y «puedo hacer `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh
ssh` al fleet» son **dos autorizaciones distintas**. La triada de Phase 3 mide
la primera: el nodo está registrado y online (`Online: true`). La segunda es el
*check mode* del SSH por la VPN — una re-auth por browser, **por operador y con
ventana de tiempo**, definida en la ACL del tailnet, que sólo se materializa
cuando intentás una sesión SSH real. Ningún campo de `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status` la
expone.

Sin esta fase el skill reporta 🟢 «conectado» y minutos después la primera
operación cross-VPS (propagación, barrido, hop a otro clon) se frena pidiendo el
link — que es exactamente lo que el operador quería saber al principio.
**La autorización pendiente se resuelve en la terminal del operador antes de
declarar que el fleet está alcanzable.** Caso real 2026-08-18: `$vpn-connect`
dio 🟢 al inicio de la sesión y `propagate-toolkit-commit.sh` salió 75 una hora
después.

1. Elegir **UN peer online que NO sea este host** de `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status`
   (columna de estado sin `offline`). Contra el host local `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ssh` falla
   con `Host key verification failed` (exit 255) — es una llamada sin sentido,
   no un problema de auth (el runbook de canales (el README junto a `config/*/expected-nodes.yml`) §Host local vs remoto).
   Sin peers online ⇒ saltar la fase, reportar `⏭️ sin peers online`.
2. Sondear con un comando **no-mutante**, sin imprimir la salida de auth.
   Timeout **≥60s** — el prompt de *check mode*
   tarda ~40s en aparecer, un `timeout 15` lo corta antes y lo disfraza de host
   caído:
   ```bash
   PEER="<peer online ≠ self>"
   timeout 60 bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ping "$PEER" >/dev/null 2>&1
   PING_RC=$?
   AUTH_PENDING=0
   timeout 60 bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ssh "ryzepeck@$PEER" true 2>&1 | {
       if grep -qiE 'to authenticate, visit|requires an additional check'; then
           exit 75
       fi
   }
   PROBE_RC=("${PIPESTATUS[@]}")
   RC=${PROBE_RC[0]}
   [ "${PROBE_RC[1]}" -eq 75 ] && AUTH_PENDING=1
   ```
3. Clasificar por el CONTENIDO, no sólo por el `rc` (mismo patrón que
   `propagate-toolkit-commit.sh`, que ya lo hace bien):
   | Señal | Veredicto |
   |---|---|
   | `AUTH_PENDING=1` | ⏸️ **auth pendiente** — autorización en la terminal del operador (paso 4) |
   | `AUTH_PENDING=0` y `RC=0` | ✅ auth SSH caliente — el fleet es alcanzable AHORA |
   | `PING_RC≠0` | ⚠️ ping sin respuesta; informar ese resultado por separado del probe SSH |
   | timeout / otro error | ⚠️ reportar el código de salida; NO imprimir la salida cruda ni afirmar que el fleet está alcanzable |
4. Si falta auth, pedile al operador que complete la conexión o el *check mode*
   en su propia terminal según el runbook de canales (el README junto a `config/*/expected-nodes.yml`),
   con el `up` y, si corresponde, la sonda SSH del runbook. Él abre el enlace
   en su navegador, sin pegarlo en ningún lado. No busques ni muestres la URL.
   Una sola autorización habilita TODOS los VPS de la ventana.
   Esperá su confirmación y repetí Phases 3-4; no reintentes a ciegas.

**Esta fase decide el veredicto final** (ver Códigos de salida): nodo conectado
con *check mode* pendiente es ⏸️, **no** 🟢.

`--no-ssh-probe` la saltea (offline, tailnet de un solo nodo, o cuando el
operador sólo quiere el estado local); entonces la fila del reporte va
`⏭️ no sondeado` y el veredicto NO puede ser 🟢 — a lo sumo ⏭️.

## Comandos de referencia

```bash
# Preflight / gate "estoy conectado?"
bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status >/dev/null 2>&1 && echo connected || echo not-connected
bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ip -4 | head -1

# Verificación post-auth
bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status
bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh status --json | jq -r '.Self.DNSName // "" | split(".")[0]'
bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --check   # (VPS) «SSH server activo en este VPS»
```

La conexión y autorización las hace el operador con el `up` del runbook de
canales, en su propia terminal; la sesión sólo guía y verifica después.

## Guardrails

- **Local-only para MUTAR**: instala y habilita el demonio de la VPN de ESTE
  host mediante `bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --apply`, nunca con sudo.
  La conexión y autorización las hace el operador en su terminal. Nunca corre comandos de trabajo en otro VPS, ni
  deploya, ni toca sus repos. **Única excepción, read-only: el probe de Phase 4**
  — un `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ssh <peer> true` que no muta nada y existe justamente para
  detectar el *check mode*. Cualquier otro `bash ~/webapps/vps-ops-toolkit/scripts/vpn/cli.sh ssh` sigue prohibido acá.
- **Idempotente**: ya-conectado ⇒ sólo reporta, no re-autentica el nodo. El probe
  de Phase 4 corre igual (es lo único que puede ver el *check mode*, y es barato
  cuando la auth está caliente: ~1-3s).
- **Nunca declares el fleet alcanzable sin haberlo probado.** «Nodo conectado»
  no implica «SSH autorizado»: son autorizaciones distintas. Si Phase 4 no corrió
  o no dio verde, el reporte lo dice y el veredicto no es 🟢.
- **No toca** el registry (`expected-nodes.yml`) ni el admin console — eso es de
  $bootstrap-vpn-fleet. La instalación y el alta del demonio local pasan por
  `bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --check` o `--apply`.
- Identificá el host ANTES de decidir `--hostname` (regla CLAUDE.md "identificar
  el host antes de llamar a la VPN").

## Códigos de salida

- `0` — nodo conectado **y** probe SSH verde (Phase 4): el fleet es alcanzable
  ahora. Es el ÚNICO caso 🟢.
- `1` — pausa manual pendiente (esperando autorización del operador en su
  terminal). Cubre la conexión de Phase 2 y el *check mode* de Phase 4 con el
  nodo ya conectado; la sesión no muestra URLs.
- `2` — error (install falló, daemon no arranca, verificación no pasa tras auth).
- `⏭️`/`0` con salvedad — probe saltado (`--no-ssh-probe` o sin peers online): se
  reporta el estado local y se dice explícitamente que el alcance al fleet **no
  se verificó**.

## Acciones disponibles

Tras el reporte, si la sesión es interactiva y NO hubo flags explícitos
(reglas de gating de $output-protocol §4), ofrecer vía AskUserQuestion:

| Opción (label) | description (costo/efecto) | preview (comando exacto) |
|---|---|---|
| Re-verificar conexión | re-corre el diagnóstico read-only (status + IP 100.x + ssh cap) | `$vpn-connect --check` |
| Registrar este nodo en el registry (dry-run primero) | preview del alta en expected-nodes.yml; el `--add-self` real commitea + pushea | `$bootstrap-vpn-fleet --add-self --dry-run` |

## Output final

Reportar siguiendo $output-protocol. Plantilla específica de esta skill:

🟢 vpn-connect OK — <host> conectado Y fleet alcanzable (IP 100.x, nodo <nombre>, probe SSH ✅)
⏸️ vpn-connect — pausa manual pendiente — autorización en la terminal del operador
   (dos causas: la conexión de Phase 2, o el *check mode* de Phase 4 con el nodo YA conectado)
🔴 vpn-connect — N error(es), revisar arriba — install/daemon falló o verificación no pasó
⏭️ vpn-connect — alcance al fleet NO verificado — `--no-ssh-probe` o sin peers online

| Dimensión | Estado | Detalle |
|---|---|---|
| Host / alias | ℹ️ | `hostname -s` + alias resuelto |
| Cliente instalado + demonio de la VPN | ✅/❌ | versión + estado mediante `bash ~/webapps/vps-ops-toolkit/scripts/vpn/bootstrap-fleet.sh --check` |
| Nodo en el tailnet | ✅/⏸️ | conectado / esperando OAuth en la terminal del operador |
| Verificación local (status + IP + ssh cap) | ✅/⚠️/❌ | IP `100.x` + nodo + ssh cap |
| **Sesión SSH al fleet (*check mode*)** | ✅/⏸️/⚠️/⏭️ | probe contra `<peer>`: alcanzable ahora / auth pendiente en la terminal del operador / error / no sondeado |
| Registro en expected-nodes.yml | ℹ️ | presente / sugerir `--add-self` |

Las dos filas del medio son **independientes**: la 4ª puede ir ✅ y la 5ª ⏸️ —
ése es justamente el caso que motivó la fase, y el reporte NO debe presentarlo
como «conectado, todo listo».

## Next steps (si aplica)
- (manual, operador) correr el `up` del runbook de canales en su propia terminal,
  abrir el enlace en su navegador y autorizar con la cuenta del fleet, sin pegarlo.
- (tras autorizar) re-correr `$vpn-connect --check` para confirmar que el
  probe pasa a ✅ antes de lanzar una operación cross-VPS larga.
- `$bootstrap-vpn-fleet --add-self` — registrar el nodo en el repo.
- (admin console) *Disable key expiry* si es un VPS.

## Referencias

- Skill de onboarding/audit/registry: $bootstrap-vpn-fleet
- Entry-point de host nuevo: $init-fleet
- Diagnóstico standalone: [`~/webapps/vps-ops-toolkit/scripts/vpn/fleet-check.sh`](../../scripts/vpn/fleet-check.sh)
- Referencia del sentinel de auth (sin capturar ni mostrar URLs): [`scripts/maintenance/propagate-toolkit-commit.sh`](../../scripts/maintenance/propagate-toolkit-commit.sh)
- CLAUDE.md sección "Acceso al fleet desde dev"
- Consola y documentación del proveedor: el runbook de canales (el README junto a `config/*/expected-nodes.yml`)
