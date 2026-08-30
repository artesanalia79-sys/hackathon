# NEXT_STEPS.md — auditoría, códigos de rechazo y reparto en dos equipos

Actualizado tras el `git pull` de `fix/ui-redesign` (4b07035) y la investigación de
códigos de decline. Diagnóstico y plan; no se cambió código de producto.

---

## 0. Estado actual

```
git pull        -> 4b07035 fix/ui-redesign (fast-forward, limpio)
npm run build   -> OK, 1.63s
make eval       -> 33/33 (nada de Python cambió en el commit)
make smoke      -> 14/14 contra la API real (gpt-4.1-mini)
```

---

## 1. Revisión del push del compañero

**Un commit, tres archivos, cero cambios en `.jsx`.**

| archivo | cambio |
|---|---|
| `design.md` | +1070 (nuevo) — spec visual Yuno: blanco dominante, Yuno Blue `#3E4FE0` |
| `ui/src/styles.css` | **+353, −0** — se *añade* al final, no reemplaza |
| `ui/package-lock.json` | −42 (campos `libc`, ruido de npm entre plataformas) |

El bundle JS quedó **byte-idéntico** (182.17 kB antes y después). Confirma que es un
rediseño puramente CSS.

**La técnica es buena.** Redefine los tokens `:root` al final del archivo (oscuro →
claro: `--bg #0b0f14 → #fafafa`, `--accent #4da3ff → #3e4fe0`), así todas las reglas
antiguas que usan `var(--…)` voltean solas. Lo verifiqué:

- 175 selectores en el bloque original, **136 sobreescritos** por el bloque nuevo.
- **0 reglas CSS con color oscuro hardcodeado quedaron sin sobreescribir.** Revisaron
  los fondos duros uno por uno (`.col.right`, `.colhead`, `.inc:hover`, `.badge.*`,
  `.btn.primary`, `pre.args`…).
- Incluso resolvieron los SVG con selectores de atributo sobre el valor literal:
  `svg [stroke="#4da3ff"] { stroke: var(--accent); }` y ocho más. Cubre `Chart.jsx` y
  `Sparkline.jsx` sin tocar JSX. Es ingenioso.

**Lo único que el CSS no puede alcanzar: 6 `style={{color:"#…"}}` inline en JSX.**
Un estilo inline gana sobre cualquier hoja de estilos sin `!important`, y el bloque
nuevo sólo usa `!important` tres veces (no para estos). Tres quedan con contraste bajo
sobre blanco:

| archivo:línea | color | qué es |
|---|---|---|
| `IncidentCard.jsx:220` | `#fbbf24` ámbar | **"Not executed. A human decides…"** — la línea que sostiene todo el pitch |
| `IncidentList.jsx:49` | `#a78bfa` lila | la etiqueta "diagnosed" en cada fila |
| `TracePanel.jsx:60` | `#34d399` verde | la línea de conclusión del agente en el trace |
| `IncidentCard.jsx:158` | `#f87171` | rojo, legible sobre blanco — OK |
| `Signature.jsx:20,21` | `#2b3b52`, `#f87171` | legibles — OK |

Arreglo: mover esos tres a clases CSS (`.notexec`, `.tag-diagnosed`, `.trace-conclude`)
y dejar que el sistema de tokens los gobierne. 10 minutos.

**Ningún hallazgo de UI de la auditoría anterior cambió**, porque no se tocó JSX: el
filtro de `superseded` sigue faltando, la confianza sigue siendo la última sección de la
tarjeta, `alertThreshold` sigue con `0.05` hardcodeado y `Injector.jsx` sigue muerto.

---

## 2. Códigos de rechazo — investigación y diagnóstico

### 2.1 Corrección: no todo es ficticio

Reviso lo que hay hoy (`api/sim/catalog.py`, `api/sim/mapping.py`): **94 entradas de
homologación, 27 códigos canónicos, 4 proveedores.** Y buena parte son reales:

| tabla | realidad |
|---|---|
| **Stripe** (25) | `insufficient_funds`, `expired_card`, `lost_card`, `stolen_card`, `do_not_honor`, `processing_error`, `issuer_not_available`, `authentication_required`… — son valores reales del enum `decline_code` de Stripe |
| **Adyen** (24) | `Authorised`, `NotEnoughBalance`, `ExpiredCard`, `BlockedCard`, `Refused`, `Referral`, `TransactionNotPermitted`, `FRAUD-CANCELLED`, `AcquirerError`, `3DNotAuthenticated` — son refusal reasons reales |
| **MercadoPago** (22) | `cc_rejected_insufficient_amount`, `cc_rejected_bad_filled_card_number`, `cc_rejected_call_for_authorize`, `cc_rejected_high_risk` — son `status_detail` reales |
| **dLocal** (23) | numéricos `300/301/305/306…` — dLocal sí usa numéricos; el mapeo fino de 302/303/304 es inventado |
| **`METHOD_CODES`** (10) | **inventados**: `pix_psp_timeout`, `nequi_push_expired`, `breb_key_not_found`, `spei_clabe_invalid`, `codi_qr_expired`, `dimo_phone_unregistered`, `oxxo_voucher_expired`… plausibles, pero no existen |
| **`NOVEL_CODES`** (4) | inventados **a propósito** — son el mecanismo del caso #8 |
| **`CANONICAL`** (27) | **inventado por nosotros**: `do_not_honor`, `lost_or_stolen`, `3ds_required`, `issuer_unavailable`… |

**El gap real no son los códigos de proveedor: es el vocabulario canónico.** Estamos
inventando nuestros propios nombres normalizados cuando existe el vocabulario de Yuno,
que es justamente el que el jurado reconoce.

### 2.2 Lo que encontré en la documentación de Yuno (más de lo que les pasaron)

`docs.y.uno` tiene tres cosas que el mensaje del contacto no menciona y que cambian el
diseño:

**(a) Mapeo a ISO 8583 por cada `response_code`.** `DO_NOT_HONOR` = ISO 05,
`INSUFFICIENT_FUNDS` = 51, `EXPIRED_CARD` = 33/54, `REPORTED_LOST` = 41,
`REPORTED_STOLEN` = 43, `USER_RESTRICTION` = 57, `RESTRICTED_BY_BANK` = 62,
`INVALID_CARD_NUMBER` = 14, `REFER_TO_CARD_ISSUER` = 01, `INVALID_MERCHANT` = 03,
`ACQUIRE_CONTINGENCY` = 22/80/90/91/92/96, `FRAUD_VALIDATION` = 34/59/63/64,
`PROVIDER_TIMEOUT` = 68, `ISSUER_VIOLATION` = 93, `DUPLICATED_TRANSACTION` = 26/94.

Esto es el ancla que nos falta: **todo adquirente de tarjeta termina hablando ISO 8583.**

**(b) Merchant Advice Codes (MAC).** Mastercard devuelve un código que *es* una
recomendación de acción, y Yuno lo normaliza: `01 UPDATE_INFORMATION`,
`02 TRY_AGAIN_LATER`, `03 DO_NOT_TRY_AGAIN`, `21 NO_RETRY_LIFE_CYCLE`,
`24–30 RETRY_AFTER_{1H,24H,2D,4D,6D,8D,10D}`, `40 NO_RETRY_POLICY`,
`42 NO_RETRY_SECURITY`, `43 MULTIPLE_USE_CARD`. El reto pide recomendar una acción — y
aquí la red misma ya la trae. Es el mejor regalo de toda la investigación.

**(c) `status` y `response_code` son dos niveles, y `DECLINED` ≠ `REJECTED` ≠ `ERROR`:**

| status | significado | nuestro modelo hoy |
|---|---|---|
| `DECLINED` | el banco dijo que no | ✅ cubierto |
| `REJECTED` | **rechazo pre-proveedor, del lado de Yuno**: validación, routing, reglas antifraude, *antes* de llegar al banco | ❌ **no existe** |
| `ERROR` | error de integración/proveedor | ✅ parcial (`raw_status=ERROR`) |
| `PENDING` | `PENDING_PROVIDER_CONFIRMATION`, `IN_REVIEW`, `CHALLENGE_REQUIRED` | ❌ no existe |

**`REJECTED` es la mina de oro que estamos desperdiciando.** Una transacción rechazada
antes del proveedor es, por definición, culpa nuestra — routing, credenciales,
antifraude propio. Es exactamente la distinción interno-vs-externo sobre la que está
construido todo el pitch, y hoy no la modelamos. Un incidente de "la conversión cae y
ningún proveedor vio la transacción" sería el caso más contundente de la demo.

### 2.3 Los otros proveedores, por país

**Brasil — ABECS es un estándar nacional obligatorio** (desde 2020-07-15) para Cielo,
Rede, Stone, PagSeguro, Getnet y todos los demás. Cada código trae un flag
**reversible / irreversible**, que es literalmente nuestra distinción soft/hard:

| ABECS | descripción | reversible |
|---|---|---|
| 05 | genérica | sí |
| 51 | saldo/limite insuficiente | sí |
| 57 | transação não permitida para o cartão | varía |
| 59 | suspeita de fraude | sí |
| 91 | emissor offline | sí |
| 96 | falha de sistema | sí |
| 78 | cartão novo sem desbloqueio | sí |
| 14 / 56 | número de cartão inválido | **no** |
| 41 / 43 | cartão perdido / roubado | **no** |
| 54 | cartão vencido | **no** |
| 58 | estabelecimento inválido | **no** |
| 62 | bloqueio temporário / cartão doméstico no exterior | varía |
| R0 / R1 | suspensão de recorrência | **no** |

Cruza limpio con Yuno: ISO 51 reversible ↔ `INSUFFICIENT_FUNDS` soft; ISO 54/41/43
irreversibles ↔ `EXPIRED_CARD`/`REPORTED_LOST`/`REPORTED_STOLEN` hard. Los dos
estándares coinciden — eso es una validación cruzada muy vendible ante el jurado.

**Colombia — PayU Latam** usa nombres semánticos, no numéricos: `APPROVED`,
`ENTITY_DECLINED`, `INSUFFICIENT_FUNDS`, `INVALID_CARD`, `EXPIRED_CARD`,
`RESTRICTED_CARD`, `ANTIFRAUD_REJECTED`, `BANK_FRAUD_REJECTED`,
`PAYMENT_NETWORK_REJECTED`, `CREDIT_CARD_NOT_AUTHORIZED_FOR_INTERNET_TRANSACTIONS`,
`BANK_UNREACHABLE`, `PAYMENT_NETWORK_NO_CONNECTION`, `ENTITY_MESSAGING_ERROR`,
`INTERNAL_PAYMENT_PROVIDER_ERROR`, `INACTIVE_PAYMENT_PROVIDER`, `EXPIRED_TRANSACTION`,
`3DS_REJECTED`, más `PENDING_TRANSACTION_{REVIEW,CONFIRMATION,TRANSMISSION}`.
**Wompi** expone `processor_response_code` crudo del adquirente (Credibanco/Redeban),
o sea ISO 8583 sin traducir.

Ojo con dos de PayU que hoy no tenemos y son muy colombianos:
`CREDIT_CARD_NOT_AUTHORIZED_FOR_INTERNET_TRANSACTIONS` (tarjeta no habilitada para
canal no presencial — clásico en CO) y `BANK_UNREACHABLE` / `ENTITY_MESSAGING_ERROR`,
que separan "el banco dijo no" de "no pudimos hablar con el banco". Esa separación es
justo lo que distingue `issuer_over_declining` de `provider_degraded`.

**México — no hay estándar nacional**, cada uno hace lo suyo: Kushki, Openpay (BBVA),
Conekta, Clip, Banorte. Kushki documenta explícitamente que los códigos de franquicia
(Visa, Mastercard y **Prosa**, el switch mexicano) llegan **de dos dígitos** — o sea ISO
8583 otra vez. La documentación pública de Openpay y Conekta está fragmentada; no
conseguí tablas completas y no las voy a inventar.

### 2.4 Conclusión de diseño

La homologación debería tener **tres capas**, no una:

```
  código crudo del proveedor        ->   ISO 8583 (cuando aplique)   ->   response_code Yuno
  "cc_rejected_insufficient_amount"      "51"                             INSUFFICIENT_FUNDS
  "NotEnoughBalance"                     "51"                             INSUFFICIENT_FUNDS
  "301"                                  "51"                             INSUFFICIENT_FUNDS
  "insufficient_funds"                   "51"                             INSUFFICIENT_FUNDS
                                                                            |
                                                             + hard/soft (retriable)
                                                             + merchant_advice_code
                                                             + category (nuestra firma)
```

Anclar en ISO 8583 nos deja añadir un proveedor nuevo escribiendo sólo su dialecto, y
nos da una respuesta preparada para "¿y si mañana entra Cielo?": *"su tabla ABECS ya es
ISO; son veinte líneas."*

---

## 3. El caso borde que planteaste: código no homologado

**Primero la buena noticia: hoy no se rompe.** Lo probé con ocho códigos inexistentes,
incluidos `None`, cadena vacía y un proveedor que no existe:

```
normalize('stripe', 'TOTALLY_NEW_CODE') -> ('unmapped:TOTALLY_NEW_CODE', 'declined', 'unknown')
normalize('stripe',  None)              -> ('unmapped:None', 'declined', 'unknown')
normalize('nosuchprovider', 'approved') -> ('unmapped:approved', 'declined', 'unknown')
```

Ninguno lanza excepción. Y la cadena completa ya existe: tipo de inyección
`unknown_code` → categoría `unknown` → regla 2 del clasificador
(`api/engine/signature.py:175`) → causa `unmapped_provider_code` → recomendación
**"Map the new provider code and re-classify the affected traffic"**. El caso #8 lo
cubre y pasa. Es decir: **el comportamiento que pediste ya está construido.**

**Pero hay tres problemas reales debajo:**

**(a) La tabla de homologación no está en el camino de conteo.**
`Generator._raw_codes` (`api/sim/generator.py:157`) deriva el código **desde** la
categoría:

```python
if category == "unknown":
    code, _m, _s = novel_code(provider)
```

Sólo las 12 transacciones de muestra por minuto (las del feed de la UI) llaman a
`normalize()`. O sea: hoy el "código desconocido" lo **afirma el inyector**, no lo
**deriva la homologación**. La detección sí consulta la tabla —`build_signature` usa
`is_known()` (`api/engine/signature.py:111-114`)— pero la emisión no.

Esto importa para el pitch: la frase "al motor nunca se le dice qué se inyectó" es
verdadera para la conversión, pero para el código desconocido el inyector está poniendo
la respuesta en la casilla. Hacer que `normalize()` sea el único punto de decisión del
camino de conteo es el trabajo de fondo, y es lo que vuelve honesta la demostración.

**(b) Un código no mapeado se fuerza a `declined`.** `api/sim/mapping.py:79` devuelve
siempre `status="declined"`. Si el proveedor devolvió `APPROVED` con un código nuevo, lo
contamos como rechazo, sin flag y sin incrementar `raw_status_mismatch`. Es el espejo
exacto de la historia del `mapping_bug` —y hoy es invisible. Un código nuevo de
aprobación debería disparar el mismo escándalo que un `mapping_bug`, o más.

**(c) Sólo hay 4 códigos novel, uno fijo por proveedor.** Un juez que inyecte
`unknown_code` dos veces ve el mismo código las dos veces.

**(d) Fuga entre proveedores.** `normalize('stripe', 'Authorised')` →
`unmapped:Authorised`. Correcto, pero es un caso de prueba que no existe: un código
válido *del proveedor equivocado* (típico de un bug de routing) hoy se reporta como
"código sin mapear" en vez de "este proveedor no debería estar devolviendo esto".

---

## 4. Hallazgos de la auditoría anterior — resumen ejecutable

Sin cambios: nada de esto se tocó en el commit del rediseño. Detalle completo y números
en el historial de la sesión; aquí la lista accionable.

| # | severidad | min | hallazgo | archivo |
|---|---|---|---|---|
| B-1 | **bloqueante** | 10 | el tablero muestra los registros `superseded`; `/api/incidents` sí los filtra. Verificado en vivo: 3 en el tablero vs 1 en la API | `IncidentList.jsx:5-7` / `routes/stream.py:33` |
| B-2 | **bloqueante** | 20 | "Cost so far" congelado en **$0**: `cost_usd` sólo se acumula dentro de `_upsert`. 3 horas simuladas de outage sumaron $0 | `engine/detector.py:334` |
| B-3 | **bloqueante** | 45 | dos fallas superpuestas → no se nombra ninguna y salen 12 registros; un change event de scope vacío secuestra la clasificación | `engine/signature.py:151,181` |
| N-1 | importante | 40 | p0 persigue el incidente: cae 10.7 puntos en 2 h y el dinero baja **41%** sin que el outage cambie | `engine/expectation.py:62` |
| N-2 | importante | 45 | la supresión de sombra se traga un segundo incidente real que comparte tráfico | `engine/detector.py:269,364` |
| N-3 | importante | 20 | "insufficient evidence" con una razón que contradice el panel de atribución de arriba | `engine/signature.py:241` |
| A-1 | importante | 15 | la confianza del agente pisa la del motor (motor 0.45 → agente **1.0** en vivo) | `agent/loop.py:262` |
| A-2 | importante | 20 | el agente escribe cifras en la prosa ("costing over $1.2M so far") y nada lo valida | `agent/tools.py:65` |
| I-1 | importante | 45/0 | tick de 25 ms → **780 ms** con tres incidentes; el reloj a 60x se queda en 35.6x. **Fijar la demo en 10x lo resuelve gratis** | `engine/cube.py` |
| I-2 | importante | 5 | `fingerprint()` ignora `kind`: los scans de integridad y conversión colisionan en un registro | `engine/incidents.py:16` |
| I-3 | importante | 20 | lectores sin lock iteran `detector.incidents` mientras el hilo de simulación inserta | `runtime.py:203,251` |
| I-5 | importante | 20 | sin supervisor ni procedimiento de reinicio (arranque en frío 2.97 s, el reloj vuelve a Wed 14:00) | — |
| P-5 | pulido | 2 | `/health` reporta la constante `SIM_SPEED`, no la real | `main.py:39` |
| P-3 | pulido | 10 | `Injector.jsx` muerto (150 líneas); `if True:` en `detector.py:233`; `alertThreshold` con `0.05` hardcodeado | varios |

**Lo que ya está bien y hay que decirlo en el Q&A:** el beta incompleto a mano tiene
error máximo **1.4×10⁻¹¹** contra scipy y **cero** decisiones que cambien de lado en el
umbral 0.99; el EWMA sí excluye la ventana bajo prueba; `avg_ticket` es por merchant ×
país (rango 49×), no global; la memoria es plana (~55 MB tras 14 horas simuladas); el
streaming del trace en vivo funciona de verdad. Y el mapa de N_MIN: sólo `method=dimo`
los domingos de madrugada queda ciego, sólo 2 de 255 combinaciones de dos dimensiones
son indetectables (`viajesya×codi`, `viajesya×dimo`), y **252 de 342 hojas nunca llegan
a N_MIN** — eso último es comportamiento correcto, no una falla; tengan la frase lista.

---

## 5. Reparto en dos equipos de dos

Propiedad de archivos disjunta, para que trabajen en paralelo sin pisarse.

| equipo | archivos que posee |
|---|---|
| **A — Motor y datos** | `api/engine/`, `api/agent/`, `api/sim/`, `api/config.py`, `api/runtime.py`, `api/main.py`, `api/routes/` |
| **B — Evaluación, UI y presentación** | `ui/`, `eval/`, `docs/`, `design.md` |

**El contrato entre los dos equipos** (acordarlo antes de escribir una línea): A publica
la lista de `response_code` canónicos y las categorías; B escribe casos contra **los
nombres canónicos**, nunca contra códigos crudos de proveedor. Así B puede escribir los
casos antes de que A termine las tablas, y no dependen uno del otro.

---

### EQUIPO A — Motor y datos

#### A1 · Motor (estadística, atribución, agente) — ~2 h

1. **I-2, 5 min** — meter `kind` en `fingerprint()`.
2. **B-2, 20 min** — acumular `cost_usd` en cada tick para todo incidente abierto, no
   sólo cuando `_upsert` dispara. Es el número falso más visible de la demo.
3. **A-1, 15 min** — techo a la confianza del agente en la del motor, no sólo por la
   puerta de `insufficient_evidence`.
4. **A-2, 20 min** — dejar de pasarle `cost_per_min_usd` y `cost_so_far_usd` al agente
   en `get_incident_summary`, o rechazar prosa con símbolo de moneda. Contradice una
   garantía que decimos en voz alta.
5. **N-3, 20 min** — causa distinta para "aislado pero sin firma reconocible", con una
   recomendación que **nombre la dimensión aislada**. Respondiendo tu pregunta: hoy dice
   "seguir observando" con una razón que contradice el panel de arriba; no, no está bien.
6. **N-1, 40 min** — congelar la contribución EWMA de un scope mientras tenga incidente
   abierto, para que el precio no se desinfle solo.

**Listo cuando:** `make eval` sigue 33/33; una corrida de 5 horas simuladas mantiene el
`$/min` dentro de ±15% del minuto 15 (hoy cae 41%); un incidente confirmado que deja de
disparar muestra un total distinto de cero.

#### A2 · Datos, catálogo e inyección — ~2 h

**Hacerlo aditivo, no un reemplazo.** Reescribir la homologación completa a mitad de
hackathon es el cambio de mayor riesgo de regresión que hay sobre la mesa: toca el
generador, las categorías y los 33 casos. El orden importa.

1. **Vocabulario canónico → Yuno, 40 min.** Reemplazar los 27 nombres inventados de
   `CANONICAL` por los `response_code` reales (`INSUFFICIENT_FUNDS`, `DO_NOT_HONOR`,
   `CALL_FOR_AUTHORIZE`, `DECLINED_BY_BANK`, `RESTRICTED_BY_BANK`, `FRAUD_VALIDATION`,
   `THREE_D_SECURE_REQUIRED`, `ACQUIRE_CONTINGENCY`, `COUNTRY_NOT_SUPPORTED`…).
   Añadir dos columnas por código: **ISO 8583** y **retriable (soft/hard)**. Esto solo
   ya cambia cómo se lee la tarjeta ante un jurado de Yuno.
2. **`normalize()` al camino de conteo, 30 min.** Que `_raw_codes` emita códigos crudos
   y la categoría salga de `normalize()`, no al revés. Es lo que vuelve honesta la frase
   "al motor no se le dijo" para el caso del código desconocido.
3. **El código no mapeado que llega como aprobación, 20 min.** Que `normalize()`
   preserve el `raw_status` del proveedor y que un `APPROVED` sin mapear cuente como
   `raw_status_mismatch` — hoy se fuerza a `declined` en silencio
   (`api/sim/mapping.py:79`). Es el espejo del `mapping_bug` y hoy es invisible.
4. **Códigos novel variados, 10 min.** Una lista por proveedor en vez de uno fijo, para
   que inyectar `unknown_code` dos veces no muestre lo mismo.
5. **Códigos de método reales o rotulados, 20 min.** Los 10 de `METHOD_CODES` son
   inventados. O se buscan los reales de PSE/Nequi/Bre-B/PIX/SPEI, o se dejan pero con
   un comentario que diga que son ilustrativos — que nadie los defienda como reales
   frente a alguien de Yuno.

**Stretch, sólo si lo anterior está verde (y decidan Q-1):** el estado **`REJECTED`
pre-proveedor**. Es la mejor historia nueva disponible —"la conversión cae y ningún
proveedor vio la transacción, luego es nuestro"— pero es una dimensión nueva en el
modelo, no un retoque.

**Listo cuando:** los `response_code` de la tarjeta coinciden con el vocabulario de Yuno;
un código crudo inventado a mano llega al conteo y sale clasificado `unknown` **por la
tabla, no por el inyector**; y un `APPROVED` sin mapear levanta un incidente de
integridad.

---

### EQUIPO B — Evaluación, UI, presentación y casos borde

#### B1 · UI y presentación — ~2 h

1. **B-1, 10 min** — filtrar `detail.superseded_by` en `IncidentList.jsx`. Con dos
   inyecciones superpuestas el tablero debe mostrar dos filas, no doce.
2. **Los 3 inline styles del rediseño, 10 min** — sacar `#fbbf24`, `#a78bfa` y `#34d399`
   de los `style={{}}` a clases CSS. Especialmente el de "Not executed. A human
   decides", que es la línea que sostiene el pitch y hoy queda ámbar sobre blanco.
3. **A-1 en pantalla, 20 min** — subir **Confidence** encima de "Recommended action" y
   marcar visualmente las tarjetas por debajo de ~0.5. Hoy la confianza es la última
   sección, ocho bloques debajo de una narración escrita en tono seguro.
4. **B-2 mitad visual, 10 min** — si `cost_usd` es 0 en un incidente confirmado, mostrar
   "—" y no "$0".
5. **P-3, 10 min** — borrar `Injector.jsx`; que `alertThreshold` venga del bloque
   `baseline` de la API en vez del `0.05` hardcodeado.
6. **Prueba de intuitividad, 20 min — esta es la de más valor y no la puedo hacer yo.**
   Sentar a quien **no** construyó la UI, sin explicarle nada, y pedirle "haz que ocurra
   una falla de pagos y dime qué se rompió". Anotar cada duda y cada clic equivocado.
7. **Revisar `design.md` contra la pantalla real, 20 min.** El spec son 1070 líneas;
   verificar que lo aplicado corresponde, y anotar qué falta para no prometer de más.

**Listo cuando:** dos inyecciones superpuestas dejan exactamente dos filas; la confianza
se ve sin hacer scroll; ningún texto queda con contraste bajo sobre blanco; y hay una
lista escrita de dónde dudó quien probó la UI por primera vez.

#### B2 · Casos borde, eval y guion — ~2 h

1. **Casos nuevos de códigos, 40 min.** Escribirlos contra los nombres canónicos, no
   contra códigos crudos, para no depender de A2:
   - **#29** código crudo nunca visto en el camino de **conteo** → categoría `unknown`,
     causa `unmapped_provider_code`, recomendación "mapear y re-clasificar", **y el
     sistema sigue operando** (falla hoy: hoy lo decide el inyector, no la tabla).
   - **#30** código sin mapear que llega como **aprobación** → debe levantar integridad,
     no contarse como decline (falla hoy).
   - **#31** código válido **del proveedor equivocado** (bug de routing) → no debe
     reportarse como "código nuevo".
   - **#32** dos códigos sin mapear de proveedores distintos a la vez → dos historias.
2. **Casos de la auditoría, 40 min.** #33 falso positivo de supresión de sombra
   (`dlocal×BR` + `itau`); #34 dos firmas en un mismo scope; #35 estabilidad a 5 horas
   (`$/min` dentro de ±15%). Escribirlos aunque fallen hoy: el criterio de "listo" es
   que **exista el caso y quede registrado su veredicto**, no que pase.
3. **Cobertura de recomendación, 30 min.** Hoy **nada** afirma la acción recomendada por
   fila de la tabla de firmas — lo único que se verifica es "keep watching" del 19e y
   `not_executed is True` del smoke. El reto pide explícitamente recomendar una acción:
   un caso por fila.
4. **DECISIONS.md + guion, 40 min.** No existe; todo vive inline como 13 marcadores
   `[changed]` en ARCHITECTURE.md, y el historial de git son cuatro commits genéricos.
   Las cinco mejores: unidades de `sim_speed` erradas por 60×; un outage de dLocal
   fragmentado en doce incidentes (por qué existe `lift`); trece registros por dos
   inyecciones; el guardarraíl de evidencia comparando ids opacos; SQLite descartado.
   Y meter al banco de preguntas el mapa de N_MIN, los números del beta vs scipy, y la
   latencia honesta del agente (**9.4–23.2 s** medidos hoy, no 10–14).

**Listo cuando:** `make eval` corre los casos nuevos con veredicto registrado;
DECISIONS.md tiene cinco entradas fechadas con la alternativa descartada; y el guion
menciona explícitamente el vocabulario Yuno y la homologación de tres capas.

---

## 6. Preguntas que necesito que decidan

1. **`REJECTED` pre-proveedor: ¿entra o no?** Es la mejor historia nueva disponible y la
   que mejor encaja con el pitch de interno-vs-externo, pero es una dimensión nueva en el
   modelo, no un retoque. Mi recomendación: **sí, pero sólo si A2 termina lo demás
   primero.**
2. **¿Reemplazamos el vocabulario canónico o lo duplicamos?** Reemplazar es lo correcto y
   lo que reconoce el jurado; también toca los 33 casos. Mi recomendación: reemplazar
   ahora, mientras el suite está verde y se puede ver qué se rompe.
3. **La escala del dinero.** No hay tope en `cost_per_min`: ViajesYa al 95% da
   **$122 641/min = $176 M/día** para un solo merchant. Es aritméticamente consistente,
   pero implica ~$1 600 M/día de GMV entre tres merchants. ¿Recalibramos `PEAK_TPM` o los
   tickets, o lo defendemos?
4. **Velocidad del reloj en la demo.** ¿Fijamos 10x (93.6% de fidelidad, seguro) o
   permitimos 60x sabiendo que con tres incidentes cae a ~36x?
5. **Supresión de sombra.** ¿Qué error prefieren delante del jurado: un segundo incidente
   real que desaparece (hoy), o registros duplicados de una misma historia?
6. **Botón Inject deshabilitado** en scopes bajo N_MIN. Impide que un juez demuestre el
   estado "insufficient evidence", que es un bullet del definition-of-done. ¿Lo abrimos?
7. **`METHOD_CODES` inventados.** ¿Buscamos los reales de PSE/Nequi/PIX/SPEI o los
   dejamos rotulados como ilustrativos? Lo segundo es honesto y cuesta 5 minutos.

---

## 7. Si sólo hay una hora

**B-1** (10 min, B1) · **B-2** (20 min A1 + 10 min B1) · **I-2** (5 min, A1) · **P-5**
(2 min, A1) · **fijar la demo en 10x** (gratis). Eso elimina todos los números falsos que
un juez puede ver en pantalla.

**Con dos horas**, sumar **A-1** y **A-2**: que el agente exagere la confianza y escriba
sus propias cifras es lo que más probablemente detecten en vivo, porque contradice una
garantía que decimos en voz alta.

**Con tres**, el punto 1 de A2 (vocabulario Yuno): es el cambio con mejor relación
esfuerzo/impacto frente a este jurado en particular.

---

## Fuentes

- [Yuno — Transaction Status and Response Codes](https://docs.y.uno/reference/payments/status-and-response-codes/transaction)
- [Yuno — HTTP Response Codes](https://docs.y.uno/reference/response-codes)
- [Cielo / ABECS — Códigos de retorno padrão](https://developercielo.github.io/tutorial/abecs-e-outros-codigos)
- [Cielo — Return codes ABECS](https://docs.cielo.com.br/ecommerce-cielo-en/page/return-codes-abecs)
- [Adyen — ABECS anuncia padronização nos motivos de recusa](https://www.adyen.com/pt_BR/centro-de-conhecimento/abecs-anuncia-padronizacao-nos-motivos-de-recusa-de-pagamentos)
- [PayU Latam — Códigos de Respuesta y Variables](https://developers.payulatam.com/latam/es/docs/getting-started/response-codes-and-variables.html)
- [Wompi — Datos de prueba en sandbox](https://docs.wompi.co/en/docs/colombia/datos-de-prueba-en-sandbox/)
- [Kushki — Error codes](https://docs.kushki.com/pe/en/getting-started/error-codes/)
- [Kushki — Error codes for card-present transactions](https://docs.kushki.com/cl/en/card-present-payments/raw-card-present-api/error-codes/)
- [Openpay — API Reference](https://documents.openpay.mx/docs/api)
