# Auditoría — Control Tower (antes de profundizar más)

Eres un revisor técnico escéptico, no el autor. Tu trabajo es encontrar por qué algo
podría estar mal, no confirmar que está bien. Ya existe SPEC.md, ARCHITECTURE.md y
UGLY_CASES.md — léelos primero, después el código real, y busca specíficamente
**donde el código y los documentos dejan de coincidir**, o donde una afirmación del
documento nunca se puso a prueba.

Reglas para esta sesión:
- No reescribas ni "arregles" nada todavía. Esto es diagnóstico, no refactor.
- Si `make eval` y `make smoke` no están en verde ahora mismo, para y repórtalo primero
  — nada de lo demás importa si eso está roto.
- Cuando algo sea una decisión de producto/alcance (no solo un bug), pregúntale al
  equipo en vez de asumir una respuesta.
- Sé específico: cita archivo y línea, no "podría haber un problema en la atribución".
- Prioriza por impacto real en la rúbrica y en la prueba de fuego, no por elegancia.

## 1. Metodología estadística — el punto de falla más silencioso

- El beta incompleto regularizado hecho a mano (`engine/stats.py` o donde viva):
  compáralo contra `scipy.stats.beta` (instálalo temporalmente si hace falta, o usa
  un script descartable fuera del repo) en un rango de `n` y `p0` realista, incluyendo
  los bordes: `n` cerca de `N_MIN`, `p0` cerca de 0 y cerca de 1 (como el PIX al
  95.5% que menciona ARCHITECTURE.md). Reporta el error máximo encontrado.
- El test es `P(rate < p0 − δ)` con score > 0.99 — ¿es de una sola cola? Confírmalo
  explícitamente: un aumento de conversión nunca debería poder disparar un incidente.
- La ventana EWMA excluye deliberadamente la ventana bajo prueba (según el doc) —
  verifica que el código realmente lo hace, no solo que el comentario lo dice.
- `N_MIN = 40`: recorre las 342 leaf cuboids (o los rollups de primer nivel) contra el
  generador sintético y lista cuáles combinaciones quedan naturalmente por debajo de
  40 tx/5min. El equipo necesita saber esto de memoria antes del domingo, no
  descubrirlo en vivo.

## 2. Atribución (Adtributor recursivo)

- Confirma que `lift` usa como denominador la participación en **attempts**, no en
  declines esperados (el doc dice que ya corrigieron esto una vez — verifica que
  sigue así en el código actual, no en la versión documentada).
- Busca o escribe un caso que no exista todavía: un incidente genuinamente distinto
  que por coincidencia comparte más de la mitad de su scope de excess con un
  incidente grande ya abierto — ¿la supresión de sombra lo suprime por error? Esa es
  la cara opuesta del caso #4 (que prueba que dos incidentes reales no se fusionan).
- Busca el caso de dos causas de firma distintas ocurriendo en el mismo scope al
  mismo tiempo (ej. un mapping bug Y un outage real de provider simultáneos) — el
  clasificador de firma es una tabla de prioridad; confirma qué pasa cuando dos
  filas aplican a la vez, y si eso es lo que el equipo realmente quiere.

## 3. Modelo de costo

- Encuentra `avg_ticket` en el código. ¿Es un valor global único, o varía por país
  o merchant? Con COP, BRL y MXN conviviendo, un promedio global daría números
  visiblemente mal calibrados para un incidente específico de un país — esto es
  rápido de confirmar y muy visible si sale mal frente al jurado.
- ¿`cost_per_min` tiene algún techo o sanity check? Prueba qué muestra la UI si casi
  el 100% de un segmento de alto ticket empieza a declinar — ¿el número se ve creíble
  o absurdo?

## 4. Recomendación (no solo diagnóstico)

- El reto pide explícitamente recomendar una acción. La tabla de firmas ya mapea
  causa → acción — pero, ¿qué recomienda el sistema cuando la atribución SÍ aísla
  dónde está el problema pero ninguna regla de firma aplica? ¿"Seguir observando" es
  lo correcto ahí, o debería al menos apuntar a la dimensión ya aislada?
- Verifica que la narración en texto libre nunca suene más segura que la confianza
  numérica que la acompaña (el caso #19e cubre el número, no necesariamente la
  prosa) — pide 2-3 ejemplos reales de narración en casos de baja confianza y léelos
  como lo leería un juez.

## 5. Resiliencia operativa

- Todo el estado vive en un solo proceso en memoria — decisión bien justificada en
  el doc. Pero: ¿ya corrió el simulador sin reiniciarse durante varias horas
  seguidas? Revisa crecimiento de memoria del deque de 260 minutos y de los
  diccionarios de incidentes/memoria bajo uso sostenido.
- ¿Qué pasa si el proceso muere a media demo? ¿Hay algún supervisor
  (systemd/pm2/lo que sea) o hay que reiniciarlo a mano? Confirma que el equipo
  sabe el procedimiento exacto y cuánto tarda.
- Verifica la latencia real del agente (documentada en 10-14s con gpt-4.1-mini)
  contra la API en este momento, no contra la medición de cuando se construyó —
  con 160 builders compartiendo cupo de OpenAI el domingo puede variar.

## 6. UI — intuitividad real, no solo que exista

- Lee los componentes de `ui/` y compara contra lo que ARCHITECTURE.md promete que
  muestra cada uno (incident card, trace panel, injector, tx feed).
- Además del código: consigue que alguien del equipo que NO construyó la UI —
  idealmente quien esté más fresco— intente inyectar un incidente sin que nadie le
  explique nada, y anota exactamente dónde duda o hace clic mal. Eso vale más que
  cualquier revisión de código para responder "es intuitivo".
- Confirma que los textos de cara al jurado (labels, botones, mensajes) están en
  inglés, incluyendo los mensajes de error y de "evidencia insuficiente".

## 7. Huecos en UGLY_CASES.md

Además de lo que ya cubre (que es mucho — el archivo es notablemente completo),
evalúa si faltan estos, y agrégalos si aplican:

- Dos fallas de firma distinta en el mismo scope, en secuencia dentro de la misma
  sesión (¿la memoria de incidentes las trata como una recurrencia o como dos
  historias distintas?).
- Sanity check del modelo de costo en un escenario de declive casi total en un
  segmento de ticket alto.
- Recomendación correcta específicamente para cada fila de la tabla de firmas, no
  solo la atribución/diagnóstico.
- Consistencia entre la narración de una audiencia (operaciones) y la otra
  (ejecutivo) para el mismo incidente — está en el roadmap del SPEC como bonus,
  confirma si ya se construyó y si tiene caso de prueba.
- Falso-positivo de supresión de sombra (ver sección 2).

## 8. Contra la rúbrica del jurado

- ¿DECISIONS.md ya captura las historias de "cambió" de ARCHITECTURE.md (el bug de
  `sim_speed`, la fragmentación en doce incidentes, el fix de handles legibles)? Esas
  son oro puro para el lente de "profundidad y criterio" — si todavía no están ahí
  como decisiones fechadas con alternativas descartadas, cópialas.
- Confirma que el trace panel realmente muestra, en vivo, cada tool call del agente
  según se ejecuta (streamed sobre SSE, según el doc) — es lo que convierte "confíen
  en nosotros" en algo que el jurado ve con sus propios ojos.

## Entregable: NEXT_STEPS.md

Al terminar, escribe `NEXT_STEPS.md` en la raíz con:

1. **Hallazgos**, ordenados por impacto real (no por orden de esta lista), cada uno
   con severidad (bloqueante / importante / pulido) y esfuerzo estimado en minutos.
2. **Preguntas para el equipo** — todo lo que sea decisión de producto, no técnica.
3. **Cuatro paquetes de trabajo independientes y sin dependencias entre sí**, uno por
   persona, usando la propiedad ya establecida: Núcleo (estadística/atribución/firma),
   Integración (infra/deploy/concurrencia/resiliencia), Superficie (UI/legibilidad),
   Producto (UGLY_CASES/decision log/guion de demo/pitch). Cada paquete de ~1-2 horas,
   con criterio de "listo" claro.
4. No toques `main` ni empieces a corregir nada — deja el diagnóstico y el reparto
   para que el equipo decida qué hacer con el tiempo que les queda.
