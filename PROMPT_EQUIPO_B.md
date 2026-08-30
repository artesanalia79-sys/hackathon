# Prompt de arranque — Equipo B (Evaluación, UI y presentación)

Pega esto como primer mensaje en su sesión de Claude Code, en la raíz del repo, después
de hacer `git pull`.

---

Eres parte del equipo **Evaluación, UI y presentación** de Control Tower (NextWave
2026, Challenge 02). Lee primero `NEXT_STEPS.md` en la raíz — es el resultado de una
auditoría completa que ya corrió `make eval` (33/33) y `make smoke` (14/14) contra la
API real, así que ambos deben seguir en verde cuando termines. No repitas ese
diagnóstico; ejecútalo.

## Tu propiedad exclusiva

`ui/`, `eval/`, `docs/`, `design.md`. No toques nada bajo `api/` — eso es del otro
equipo (Motor y datos), y trabajan en paralelo sobre el mismo repo.

## Contexto que necesitas antes de tocar nada: el rediseño ya está en `main`

Un compañero ya subió `fix/ui-redesign` (commit `4b07035`): 1070 líneas de
`design.md` con la dirección visual (Yuno Blue `#3E4FE0`, blanco dominante) y +353
líneas al final de `ui/src/styles.css` que voltean toda la interfaz de oscuro a claro
redefiniendo los tokens `:root`. Es sólido — 136 de 175 selectores originales quedaron
sobreescritos, incluidos los SVG de los charts vía selectores de atributo, y ninguna
regla CSS con color oscuro quedó suelta. El bundle JS es byte-idéntico: no tocó ningún
`.jsx`. Antes de tu primera tarea de UI, corre `npm run build` para confirmar que
sigue compilando igual (182.17 kB).

## El contrato con el otro equipo (Motor y datos)

Ellos van a publicar una lista de `response_code` canónicos alineados con Yuno
(`INSUFFICIENT_FUNDS`, `DO_NOT_HONOR`, etc., en vez de los nombres inventados que hay
hoy). **Escribe tus casos de prueba nuevos contra esos nombres canónicos, no contra
códigos crudos de proveedor** — así no dependes de que ellos terminen todo antes de que
tú empieces.

## Tareas, en orden de impacto real (ver NEXT_STEPS.md §5, paquetes B1 y B2 para el detalle completo)

### B1 — UI y presentación (~2h)

1. **El tablero muestra registros que la API oculta (bloqueante, 10 min).**
   `ui/src/components/IncidentList.jsx:5-7` filtra sólo por `status`, nunca por
   `detail.superseded_by` — y `App.jsx` alimenta esa lista desde el snapshot SSE
   (`api/routes/stream.py`, no lo toques), que no filtra. Verificado en vivo: dos
   inyecciones superpuestas dejaron 3 registros en el tablero y 12 en un caso más
   extremo, cuando debían ser 2. Arregla el filtro en `IncidentList.jsx`.
2. **Tres colores inline del rediseño quedaron sin voltear (10 min).** El sistema de
   tokens no alcanza `style={{color:"#..."}}` en JSX. Tres quedan con contraste bajo
   sobre el nuevo fondo blanco:
   - `IncidentCard.jsx:220` — `#fbbf24` en *"Not executed. A human decides…"*, la
     línea que sostiene el pitch de "recomienda, nunca ejecuta".
   - `IncidentList.jsx:49` — `#a78bfa` en la etiqueta "diagnosed".
   - `TracePanel.jsx:60` — `#34d399` en la línea de conclusión del agente.
   Muévelos a clases CSS (`.notexec`, `.tag-diagnosed`, `.trace-conclude`) definidas
   con `var(--warn)`/`var(--purple)`/`var(--ok)` para que el sistema de tokens los
   gobierne igual que todo lo demás.
3. **La confianza es la última sección de la tarjeta (20 min).** Hoy está ocho
   bloques debajo de una narración del agente escrita en tono seguro incluso cuando la
   confianza real es baja (medido en vivo: motor 0.45 → agente mostró 1.0). Sube
   **Confidence** encima de "Recommended action" en `IncidentCard.jsx`, y dale un
   tratamiento visual distinto cuando esté por debajo de ~0.5 (no esperes a que el
   otro equipo arregle el número — el problema de visibilidad es tuyo, el del techo al
   valor es de ellos).
4. **"Cost so far" en $0 se lee como texto normal (10 min).** Mientras el otro equipo
   arregla la acumulación real, en `IncidentCard.jsx` haz que si `cost_usd` es 0 en un
   incidente `confirmed`, se muestre "—" en vez de "$0" — evita que se lea como un
   número real y congelado.
5. **Limpieza (10 min).** Borra `ui/src/components/Injector.jsx` (150 líneas, no lo
   importa nadie desde el rediseño de Injector.jsx a InjectPanel.jsx). En
   `IncidentCard.jsx`, saca el `- 0.05` hardcodeado del `alertThreshold` del chart y
   tráelo del bloque `baseline` que ya devuelve la API.
6. **Prueba de intuitividad — la más valiosa, hazla en persona (20 min).** Sienta a
   alguien del equipo que **no** construyó la UI, sin explicarle nada, y pídele "haz
   que ocurra una falla de pagos y dime qué se rompió". Anota cada duda y cada clic
   equivocado. Esto vale más que cualquier revisión de código para responder si el
   sistema es intuitivo.
7. **Confirma `design.md` contra la pantalla real (20 min).** El spec tiene 1070
   líneas; verifica que lo aplicado corresponde y anota qué falta, para no prometer de
   más frente al jurado.

**Listo cuando:** dos inyecciones superpuestas dejan exactamente dos filas visibles;
la confianza se ve sin hacer scroll; ningún texto queda con contraste bajo sobre
blanco; y tienes una lista escrita de dónde dudó la persona que probó la UI por
primera vez.

### B2 — Casos borde, eval y guion de demo (~2h)

1. **Casos nuevos sobre códigos no homologados (40 min).** Escríbelos contra nombres
   canónicos (`INSUFFICIENT_FUNDS`, etc.), no códigos crudos, para no bloquearte con
   el otro equipo:
   - **#29** un código crudo nunca visto llega al **camino de conteo agregado** (no
     sólo al feed de muestra) → categoría `unknown`, causa `unmapped_provider_code`,
     recomendación "mapear y re-clasificar", **y el sistema sigue operando sin
     romperse**. Hoy falla porque el inyector decide la categoría directamente en vez
     de que la tabla de homologación la derive — es justo el caso borde que
     preguntaste si podía presentarse, y la respuesta es: sí, y hoy el sistema no lo
     prueba de verdad.
   - **#30** un código sin mapear que llega como **aprobación** debe levantar un
     incidente de integridad, no contarse silenciosamente como decline.
   - **#31** un código válido pero **del proveedor equivocado** (bug de routing) no
     debe reportarse como "código nuevo sin mapear".
   - **#32** dos códigos sin mapear de proveedores distintos a la vez → dos historias
     separadas, no una fusionada.
   Escríbelos aunque hoy fallen — el criterio de "listo" es que el caso exista y su
   veredicto quede registrado en `docs/UGLY_CASES.md`, no que pase ya.
2. **Casos de la auditoría (40 min).** Igual, aunque fallen hoy:
   - **#33** falso positivo de supresión de sombra: `dlocal×BR` + `itau` (issuer
     brasileño) inyectados a la vez deben separarse en dos incidentes, no fusionarse
     en uno.
   - **#34** dos causas de firma distinta en el mismo scope al mismo tiempo (p.ej.
     `mapping_bug` + `provider_degraded` en `dlocal`) deben producir como máximo dos
     registros visibles, no doce.
   - **#35** estabilidad a 5 horas simuladas: con una inyección de severidad fija sin
     cambios, el `$/min` mostrado debe quedarse dentro de ±15% de su valor en el
     minuto 15.
3. **Cobertura de recomendación (30 min).** Hoy nada verifica que la acción
   recomendada corresponda a cada fila de la tabla de firmas — sólo existe el caso
   19e ("keep watching" cuando hay poca evidencia) y el smoke test verificando
   `not_executed is True`. El reto pide explícitamente recomendar una acción: escribe
   un caso por cada fila de `RECOMMENDATION` en `api/engine/signature.py` que
   confirme que la acción mostrada es la esperada para esa causa.
4. **`DECISIONS.md` + banco de preguntas (40 min).** No existe hoy; todo vive inline
   como 13 marcadores `[changed]` en `docs/ARCHITECTURE.md`, y el historial de git no
   ayuda (cuatro commits genéricos). Créalo con entradas fechadas, cada una con la
   alternativa que se descartó y por qué. Las cinco más fuertes para "profundidad y
   criterio":
   - unidades de `sim_speed` erradas por 60× (por qué existe el caso #27),
   - un outage real de dLocal fragmentado en doce incidentes distintos (por qué existe
     `lift` en el atributor),
   - trece registros abiertos por sólo dos inyecciones en una hora (folding al crear),
   - el guardarraíl de evidencia del agente comparando ids opacos de la API en vez de
     handles legibles, que rechazaba toda respuesta honesta,
   - SQLite descartado a favor de un único dueño de estado en memoria.
   Añade al banco de preguntas del jurado: el mapa de N_MIN (qué segmentos nunca
   alcanzan la muestra mínima — es comportamiento correcto, no una falla), los
   números del beta hecho a mano contra scipy (error máximo 1.4×10⁻¹¹), y la latencia
   real del agente medida hoy (9.4–23.2 s, no los 10–14 s que dice el README).

**Listo cuando:** `make eval` corre los casos #29–35 con un veredicto registrado
(pase o no); `DECISIONS.md` existe con al menos cinco entradas fechadas y su
alternativa descartada; y el guion de demo menciona el vocabulario Yuno y el mapa de
N_MIN.

## Una decisión que no es tuya

El botón de Inject está deshabilitado para scopes por debajo de la muestra mínima
(`InjectPanel.jsx`), lo que impide que un juez vea en vivo el estado "insufficient
evidence" — un punto explícito del definition-of-done. No lo cambies sin que el equipo
lo acuerde; sólo que sepan que es una opción sobre la mesa.

Al terminar cada tarea, corre `make eval` (y `npm run build` si tocaste UI) y anota en
tu propio resumen qué pasó de verde a rojo, si algo.
