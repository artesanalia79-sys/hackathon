# Prompt de arranque — Equipo A (Motor y datos)

Pega esto como primer mensaje en su sesión de Claude Code, en la raíz del repo, después
de hacer `git pull`.

---

Eres parte del equipo **Motor y datos** de Control Tower (NextWave 2026, Challenge 02).
Lee primero `NEXT_STEPS.md` en la raíz — es el resultado de una auditoría completa que
ya corrió `make eval` (33/33) y `make smoke` (14/14) contra la API real, así que ambos
deben seguir en verde cuando termines. No repitas ese diagnóstico ni el de
`docs/UGLY_CASES.md`; ejecútalo.

## Tu propiedad exclusiva

`api/engine/`, `api/agent/`, `api/sim/`, `api/config.py`, `api/runtime.py`,
`api/main.py`, `api/routes/`. No toques nada bajo `ui/`, `eval/` ni `docs/` — eso es
del otro equipo, y trabajan en paralelo sobre el mismo repo.

## El contrato con el otro equipo (Evaluación/UI/Presentación)

Ellos van a escribir casos de prueba nuevos contra **los nombres canónicos de
`response_code`** que tú definas, no contra códigos crudos de proveedor. Publica esa
lista (aunque sea provisional) apenas la tengas — no los bloquees esperando a terminar
todo lo demás.

## Tareas, en orden de impacto real (ver NEXT_STEPS.md §5, paquetes A1 y A2 para el detalle completo)

### A1 — Motor (haz esto primero, ~2h)

1. **`fingerprint()` ignora `kind`** (`api/engine/incidents.py:16`) — el scan de
   integridad y el de conversión pueden colisionar en un mismo registro sobre el mismo
   proveedor. Añade `kind` al hash. 5 min.
2. **"Cost so far" se congela en $0** — `rec.cost_usd` sólo se acumula dentro de
   `_upsert` (`api/engine/detector.py:334`). Un incidente confirmado que deja de
   disparar en la ventana de 5 min dejó de sumar dinero en una prueba de 3 horas
   simuladas. Acumúlalo en cada tick para todo incidente abierto. 20 min.
3. **La confianza del agente pisa la del motor** — hoy sólo se limita por la puerta de
   `insufficient_evidence` (`api/agent/loop.py:262`). Medido en vivo: motor 0.45 →
   agente 1.0 en la tarjeta. Pon un techo general. 15 min.
4. **El agente escribe cifras en su propia prosa** — `get_incident_summary`
   (`api/agent/tools.py:65-66`) le pasa `cost_per_min_usd` y `cost_so_far_usd` al
   modelo, y nada valida que no las repita en `exec_line`/`ops_explanation`. Ya se vio
   "costing over $1.2M so far" escrito por el agente. Quita esos campos del tool o
   rechaza prosa con símbolo de moneda. Contradice una garantía que decimos en el
   pitch. 20 min.
5. **"Insufficient evidence" con una razón que se contradice a sí misma**
   (`api/engine/signature.py:241`) — cuando la atribución SÍ aísla un scope pero
   ninguna fila de la tabla de firmas aplica, hoy dice "the excess does not
   concentrate anywhere" justo debajo del panel que muestra que sí concentró. Dale una
   causa distinta que nombre la dimensión aislada. 20 min.
6. **p0 persigue el incidente** (`api/engine/expectation.py:62`) — en una corrida de 5
   horas simuladas sin cambiar el injection, el `$/min` mostrado cayó 41% solo porque
   el EWMA absorbe el propio incidente. Congela la contribución EWMA de un scope
   mientras tenga un incidente abierto. 40 min.

**Listo cuando:** `make eval` sigue 33/33; una corrida de 5 horas mantiene `$/min`
dentro de ±15% de su valor en el minuto 15; un incidente confirmado que deja de
disparar en la ventana corta muestra un total que sigue creciendo.

### A2 — Datos, catálogo e inyección (~2h, aditivo, no reemplazo agresivo)

El riesgo más alto de toda la sesión es reescribir la homologación a la mitad del
hackathon y romper los 33 casos. Haz esto en el orden dado, corriendo `make eval`
después de cada paso.

1. **Vocabulario canónico → Yuno (40 min).** `api/sim/mapping.py` — `CANONICAL` tiene
   27 nombres inventados por nosotros (`do_not_honor`, `lost_or_stolen`,
   `3ds_required`...). Reemplázalos por los `response_code` reales de Yuno:
   `INSUFFICIENT_FUNDS`, `DO_NOT_HONOR`, `CALL_FOR_AUTHORIZE`, `DECLINED_BY_BANK`,
   `RESTRICTED_BY_BANK`, `FRAUD_VALIDATION`, `THREE_D_SECURE_REQUIRED`,
   `ACQUIRE_CONTINGENCY`, `COUNTRY_NOT_SUPPORTED`, `CURRENCY_NOT_ALLOWED`,
   `REFER_TO_CARD_ISSUER`, `ISSUER_VIOLATION`, `TERMINAL_ERROR`, `UNKNOWN_ERROR`, etc.
   (lista completa con su categoría hard/soft y su código ISO 8583 en
   `NEXT_STEPS.md §2.2`). Añade dos columnas por entrada: **ISO 8583** y
   **retriable**. Fuente: https://docs.y.uno/reference/payments/status-and-response-codes/transaction
2. **`normalize()` al camino de conteo real (30 min).** Hoy `Generator._raw_codes`
   (`api/sim/generator.py:157`) decide el código *desde* la categoría que ya asumió el
   inyector — la tabla de homologación sólo la consultan las 12 transacciones de
   muestra del feed de la UI, no el conteo agregado. Invierte el orden: que
   `normalize()` sea quien decida `unknown` a partir de un código crudo, no que el
   inyector lo afirme directamente. Esto es lo que hace honesta la frase "al motor
   nunca se le dice qué se inyectó" para el caso del código no mapeado.
3. **Un código no mapeado que llega como aprobación (20 min).**
   `api/sim/mapping.py:79` fuerza siempre `status="declined"` en lo no mapeado. Si el
   proveedor devolvió `APPROVED` con un código nuevo, hoy se cuenta como rechazo sin
   ninguna señal. Preserva el `raw_status` real y, si es `APPROVED` sin mapear, que
   incremente `raw_status_mismatch` — es el espejo exacto de la historia del
   `mapping_bug` y hoy es invisible.
4. **Códigos "novel" variados (10 min).** `NOVEL_CODES` en `api/sim/catalog.py` tiene
   uno fijo por proveedor. Inyectar `unknown_code` dos veces muestra siempre el mismo
   código. Da una lista corta por proveedor y elige uno al azar por inyección.
5. **`METHOD_CODES` inventados (20 min).** Los 10 de `api/sim/catalog.py` (`pix_psp_timeout`,
   `nequi_push_expired`, etc.) son plausibles pero no existen. O investigas los reales
   de PSE/Nequi/Bre-B/PIX/SPEI, o los dejas con un comentario que diga que son
   ilustrativos — que nadie los defienda como reales frente al jurado.

**No hagas todavía** (son decisión de producto, ver preguntas abajo): el estado
`REJECTED` pre-proveedor como dimensión nueva del modelo.

**Listo cuando:** los `response_code` en la tarjeta coinciden con el vocabulario de
Yuno; un código crudo inventado a mano llega al conteo y sale clasificado `unknown`
**por la tabla**, no por el inyector; un `APPROVED` sin mapear levanta un incidente de
integridad; `make eval` sigue 33/33 después de cada paso.

## Preguntas que no debes decidir solo — pregúntale al equipo

1. **¿Añadimos el estado `REJECTED` pre-proveedor?** Es la mejor historia nueva
   disponible (conversión cae, ningún proveedor vio la transacción → es nuestro), pero
   es una dimensión nueva en el modelo, no un retoque. Sólo si A2 termina lo demás con
   tiempo de sobra.
2. **La escala del dinero** — no hay tope en `cost_per_min`; un caso extremo da
   $176M/día para un solo merchant. ¿Recalibramos `PEAK_TPM`/tickets o lo defendemos
   tal cual?
3. **Supresión de sombra** (`api/engine/detector.py:269,364`) — hoy un segundo
   incidente real que comparte tráfico con uno grande se suprime en vez de mostrarse
   aparte. Verificado con dos inyecciones reales. ¿Prefieren ese error o el opuesto
   (registros duplicados de una misma historia)? No lo arregles sin acordarlo, cambia
   el comportamiento de un caso ya verde (#4).

Al terminar cada tarea, corre `make eval` y anota en tu propio resumen qué pasó de
verde a rojo, si algo. No toques `main` directo si el equipo prefiere revisar antes —
confirma con ellos el flujo de rama/PR antes de empezar si no está claro.
