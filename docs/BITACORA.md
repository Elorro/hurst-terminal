# Bitácora de sesión — Terminal Nasdaq

*Engineering logbook (Spanish): the working record of decisions, reversals and
verifications, kept in the author's primary working language.*

> Sesión de arquitectura y arranque de Fase 1. Registro de decisiones, hallazgos
> verificados y pendientes. Sirve como input del brief de Fase 2.
> Fecha de sesión: sábado 2026-06-20.

---

## 1. Estado del proyecto al cerrar la sesión

**Fase 1 (esqueleto de datos): cerrada, salvo verificación de Live en vivo.**

- Backend en Python que conecta a Alpaca, recibe velas OHLC de AMD/NVDA y las
  imprime por consola.
- Probado con `ReplaySource` sobre el lunes 2026-06-15: 785 velas, sesión
  completa (pre-market 08:14 ET → cierre 15:59 ET), OHLC coherente, timestamps
  alineados a ET. Sin truncamiento.
- `LiveSource` (modo A) cableado y verificado a nivel de import; su prueba en
  vivo queda pendiente porque requiere mercado abierto.

---

## 2. Decisiones tomadas en sesión (no reabrir sin motivo)

### Entorno
- **Python 3.14** confirmado viable. Verificado contra PyPI que `alpaca-py 0.43.4`
  tiene rangos de dependencias abiertos hacia arriba y que existen wheels `cp314`
  de `pydantic-core`, `aiohttp` y `msgpack`. En la instalación real, `msgpack`
  llegó como wheel precompilado — NO compiló. El único comodín del brief quedó
  descartado.
- venv obligatorio (`python3.14 -m venv .venv`), no instalar en Python del sistema.

### Arquitectura de fuente de datos
- **Fuente polimórfica**: interfaz común `DataSource`; dos implementaciones
  intercambiables (`LiveSource` vía WebSocket, `ReplaySource` vía REST histórico
  + reloj) que emiten `Bar` por el mismo canal. El consumidor no sabe de cuál
  vienen. Cambiar de fuente es solo config.
- Interfaz vía **async generator** (`stream()`), no callbacks.
- **Validar primero con Replay** (determinista, corre a cualquier hora), luego
  Live. Esto separa "¿la fuente conecta?" de "¿el agregador agrega bien?".
- Razón de fondo del replay: el caso de uso principal es estudiar reacciones a la
  Fed (FOMC ~14:00 ET, fechas conocidas). El replay no es solo para depurar; es
  la herramienta de estudio. Y desacopla el desarrollo del horario de mercado.

### Modo live
- **A-con-B-detrás-de-flag**: modo A (suscribirse a `bars` ya agregadas) por
  defecto; modo B (suscribirse a `trades` y agregar OHLC a mano) cableado pero
  desactivado, fuera del camino crítico.

### Fuente de datos / SDK
- Alpaca, plan gratuito, feed IEX explícito (`DataFeed.IEX`).
- Clases: `StockDataStream` (live), `StockHistoricalDataClient` + `StockBarsRequest`
  (replay).
- Credenciales de **paper trading** desde `.env` local (en `.gitignore`),
  nunca hardcodeadas ni compartidas en chat/repo.
- `REPLAY_DATE` configurable; usar día de mercado reciente (no hoy/ayer, no
  finde, no festivo).

---

## 3. Hallazgos verificados sobre el feed gratuito IEX

- **Recency**: el plan gratuito bloquea datos SIP recientes (<15 min); datos
  >15 min accesibles. Para replay de días pasados → sin problema.
- **Profundidad histórica**: barras IEX desde ~mediados de 2020 (SIP desde ~2017).
- **Recorte ~9h**: había reporte de usuarios de que el plan gratuito recortaba la
  profundidad pese a los parámetros. **NO apareció** en la corrida del 2026-06-15.
  Descartado para este caso de uso.
- **Velas planas en pre-market** (O=H=L=C): comportamiento esperado del feed IEX
  (poco flujo, a veces una sola transacción o ninguna por minuto). NO es bug.
- **Horario**: el feed live de barras solo fluye 9:30–16:00 ET. Fuera de eso no
  llegan barras y no está roto.

---

## 4. Pendientes inmediatos (lunes, mercado abierto)

- [x] **Verificar Live en vivo** (§7): que `LiveSource` (modo A) imprima velas en
      sesión.
- [x] **Medir latencia de cierre de vela** (§7, línea base): que la barra del minuto X aparezca
      poco después de cerrar el minuto X, no con retraso grande. Esto determina
      si el Hurst en vivo irá al día o arrastrado. Es el detalle que separa
      "funciona en replay" de "sirve en vivo".

---

## 5. Decisiones de diseño para Fase 2 (Hurst rolling) — pensar ANTES de codear

### Filtrar pre/post-market antes de calcular Hurst (importante)
- Las velas planas de pre-market (O=H=L=C por baja cobertura IEX) **sesgarían el
  DFA**: una racha de precios casi idénticos parece artificialmente persistente
  o rompe el cálculo de fluctuación.
- Esa baja "rugosidad" del pre-market es un **artefacto de cobertura de datos**,
  no del mercado. El Hurst lo mediría como señal cuando es ausencia de datos.
- **Decisión a tomar en Fase 2**: probablemente filtrar a horario regular
  (9:30–16:00 ET) antes de medir régimen. Dejarlo como parámetro consciente, no
  como default silencioso.

### Recordatorios de filosofía (de la spec, no olvidar)
- Hurst/dimensión fractal = **diagnóstico de régimen**, no señal de timing.
- H>0.5 tendencia / H<0.5 reversión / H≈0.5 aleatorio.
- Verlo **migrar** en ventanas móviles; el H global es casi inútil.
- **No** optimizar umbrales para señales automáticas (riesgo de sobreajuste;
  mismo error que la cointegración ya descartada en vivo).
- El valor de H depende del tamaño de ventana — no hay un H "verdadero" único.
- En datos reales la señal es más sucia que en sintéticos.

---

## 6. Notas de producto / alcance (discutidas en sesión)

- **No reemplazar TradingView.** El valor único es el Hurst/fractal en vivo, que
  TradingView no tiene. Construir paridad de funciones con TradingView es tiempo
  perdido. Flujo realista: thinkorswim/TradingView para gráfico+ejecución; esta
  terminal como capa de contexto de régimen en segunda pantalla.
- Reconsiderar standalone solo **con evidencia de uso real** de que el panel de
  Hurst cambia decisiones. No por anticipado.
- El mayor riesgo del proyecto ahora no es técnico, es de **alcance**: la
  tentación de que crezca hasta competir con algo que no necesita competir.
  
## 7. Cierre de Fase 1 — verificación Live (lunes 2026-06-22)

- LiveSource (modo A) verificado en vivo: AMD y NVDA, 56 barras de 1m en ~28 min.
- Latencia de cierre de vela (1m), línea base día tranquilo, reloj NTP-sincronizado:
  - mediana 0.27–0.28 s / p95 0.36–0.37 s / max 0.42 s — sin colas, estable.
- 5m derivada por BarResampler (agregación local, no suscripción aparte):
  cross-check vs Alpaca 4/4 ventanas completas, OHLCV exacto. Ventanas incompletas
  (IEX sin barra en algún minuto / captura a mitad de ventana) detectadas y excluidas.
- Truncamiento IEX (§5.3 / "recorte ~9h"): no apareció. Descartado para este uso.
- Archivos: backend/latency_logger.py, backend/aggregator.py (BarResampler +
  OHLCAggregator), backend/validate_live.py. Reproducir: validate_live.py 28 (en horario).
- FASE 1 CERRADA por ambos lados (replay determinista + live validado).
- Pendiente real para confianza plena: repetir la medición de latencia en sesión
  FOMC (14:00 ET) y comparar contra esta línea base. Hoy = piso de referencia, NO
  el caso de estrés.
  
## 8. Decisión de diseño Fase 2 — Filtrado y segmentación del Hurst (martes 2026-06-23)

> Decisión de papel (mercado casi cerrado, buffer se llena mañana). Cierra y
> precisa lo que §5 dejó como "probablemente filtrar". Input directo del brief
> de Fase 2 a Claude Code.

### Arquitectura: el filtro va en el borde de entrada al buffer, NO en dfa()
- `dfa()` se queda **pura**: recibe serie limpia 1D, calcula. Así sigue validable
  contra los sintéticos de `hurst_dfa.py`. Reutilizar sin modificar.
- Separación: `SessionFilter` (qué barra cuenta) → buffer (mantiene ventana +
  segmenta) → `dfa()` (solo calcula).
- El módulo consume del `DataSource` polimórfico vía `stream()`; idéntico con
  Live y Replay.

### Tres capas de filtrado
- **Sesión regular 9:30–16:00 ET.** Filtro duro por timestamp: `09:30:00 <= ts 
  16:00:00`. Hora ET vía `zoneinfo` (`America/New_York`), **nunca** offset UTC
  hardcodeado (debe sobrevivir al cambio EDT/EST). Recordar convención Alpaca:
  el ts marca el **inicio** del minuto (primera válida 09:30:00, última 15:59:00).
- **Velas planas (O=H=L=C).** Excluir **incluso dentro** de sesión regular.
  Artefacto de baja cobertura IEX (§3). Colapsan la varianza residual del
  `polyfit` local → H falso pero plausible (parece súper-persistente; una recta
  es máximamente "suave"). No lanzan excepción: engañan en silencio.
- **Segmentación por contigüidad temporal.** Se **invierte** la opción inicial:
  en vez de concatenar ignorando huecos, se segmenta. Un retorno multi-minuto
  colado como de 1m es outlier de magnitud que corre el H de la ventana. El sesgo
  sería marginal en sesión tranquila, pero alrededor de 14:00 FOMC los huecos
  pueden NO ser raros — optimizar para lo tranquilo es aceptar el riesgo justo
  en el régimen que se vino a estudiar.

### Reglas de segmentación
- **Corte** cuando el gap real entre ts consecutivos **> 2 min**. Contiguas = 60s;
  una barra faltante = 120s; un solo minuto faltante se tolera. Umbral fijado por
  **física del dato, NO calibrable** — no es un dial para buscar un H "bonito".
- **Cruce de día corta SIEMPRE** (el retorno overnight no es intradía).
- Ventana sin segmento contiguo de longitud ≥ tamaño completo → **H = NaN**.
  No correr DFA sobre datos rotos; preferir hueco visible a H inventado.
  Coherente con el manejo de buffer no lleno de Fase 1.

### Observabilidad (NO mitigación)
- Loggear por sesión: barras excluidas (fuera de sesión / planas) y ventanas
  anuladas a NaN (buffer incompleto / segmentación).
- El registro **no reduce** el sesgo del hueco; solo avisa. Pero la ausencia
  **es dato de régimen**: muchas ventanas NaN alrededor de 14:00 = mercado
  paralizado pre-anuncio. Verlo, no enterrarlo.

### Costo reconocido y aceptado
- Ventana 120 + mínimo `dfa()` ~50: un hueco que parta la ventana (p. ej. 70+45)
  deja sin segmento válido aunque haya 115 barras buenas. Se pueden perder más H
  de los esperados en sesiones fragmentadas.
- Si en una FOMC real se pierde mucho H cerca de 14:00 → **NO** "aflojar el
  umbral". Significa que IEX no tiene resolución para ese minuto: límite real de
  la herramienta, hay que conocerlo antes de confiar en ella.

### Guardia anti-sobreajuste: verificación ≠ calibración
- Replay sobre fecha FOMC pasada SOLO para confirmar que (a) los cortes caen donde
  hay huecos reales y (b) el conteo de NaN es comprensible. El replay **no** elige
  el umbral. Pensar "con otro umbral se ve más estable" → parar; eso es sobreajuste.

### Pendiente Fase 2 (Claude Code)
- [x] `SessionFilter` (capas sesión + velas planas) en el borde de entrada (§9).
- [x] Buffer rolling + segmentación por contigüidad (gap > 2 min, H=NaN sin
      segmento suficiente) (§9).
- [x] Logging de barras excluidas y ventanas anuladas por sesión (§9, §10).
- [x] Mantener `dfa()` pura; reutilizar la de `hurst_dfa.py` sin tocar (§9).
- [x] Verificación (no calibración) vía replay de fecha FOMC pasada — fecha
      elegida: 2026-06-17 (§9).

### Ideas futuras registradas (NO construir ahora)
- Otras lentes de régimen que encajan con la filosofía diagnóstica: **change-point
  detection** (pareja natural del Hurst para el caso Fed: régimen + momento del
  cambio) y **HMM** (formaliza con probabilidad lo que ahora se hace con umbral).
  Ambas diagnósticas, no gatillos.
- Panel de noticias/social en tiempo real: fase muy posterior, base sería el
  endpoint de noticias gratuito de Alpaca. Fuera de alcance actual.

## 9. Verificación FOMC, hallazgo AMD y preparación NFP (mar 2026-06-30 / mié 2026-07-01)

### Verificación replay FOMC 2026-06-17 (fecha fijada de antemano, §8)
- Ambos objetivos de la guardia anti-sobreajuste (§8) **cumplidos**: cortes sobre
  huecos reales, conteo de NaN comprensible.
- **NVDA limpia**: 390 barras contiguas, 270 H, 0 cortes.
- **AMD**: 333 válidas, 11 cortes — todos sobre huecos reales ≥180 s; 27 gaps de
  120 s tolerados; conteo NaN exacto (120+211+2 = 333). Off-by-one verificado en
  ambas direcciones.

### Hallazgo contra-intuitivo: los huecos van ANTES del anuncio
- Los huecos IEX de AMD se concentran en el **lull pre-anuncio** (12:11–13:53 ET),
  NO en/después de las 14:00. Post-anuncio AMD queda totalmente contigua
  (volumen alto → IEX imprime cada minuto).
- **Invierte la asunción con la que se diseñó §8**: la herramienta ve bien la
  reacción; la ceguera potencial está en la antesala.

### AMD-1m-IEX: sin señal utilizable
- Dos datapoints: 15-jun (tranquilo) run máx 109 → 0 H; 17-jun (FOMC) run máx
  122 → 2 H (15:58, 15:59).
- AMD a 1m **roza el umbral de 120** y es día-dependiente → sin señal utilizable.
- **Causa raíz: resolución del feed, no la ventana.**

### Decisión tomada — opción (a): AMD migra a 5m
- AMD → **5m / ventana 60** vía `BarResampler` (§7); NVDA se queda en 1m/120.
- Escalas **no comparables entre sí**: aceptado y documentado.
- **Descartado**: ventana-por-símbolo a 1m (arregla el síntoma, rompe
  comparabilidad).
- Ventana 60 fijada por **física** (`dfa()` ≥50, sesión = 78 barras de 5m),
  **NO calibrable** (coherente con §8).

### Diagnóstico corregido (de resumen externo)
- Las velas planas **NO contaminan** nuestro DFA: `SessionFilter` las excluye (§8).
- Nuestro problema es **contigüidad/cobertura**, no retornos-cero. El remedio 5m
  se justifica por el **colapso de huecos al agregar**, no por dilución.

### Tarea A — captura Live sesión NFP (jue 2026-07-02)
- NFP 8:30 ET **pre-market → invisible al pipeline** (filtro de sesión, §8);
  viernes 3 festivo.
- **Primera corrida del motor Hurst sobre `LiveSource`.** NO es el estrés FOMC
  (ese: 28–29 jul).
- Conflicto de brief detectado por Claude Code y resuelto: "latencia en paralelo"
  + "sin cambios de código" imposible con 1 WebSocket concurrente (plan gratuito).
  Resuelto: wiring **aditivo** de `LatencyLogger` en `run_hurst.py`; motor byte a
  byte intacto.
- Smoke tests OK:
  - Replay 17-jun → H/NaN **idénticos** a la verificación previa (prueba de
    aditividad).
  - Plumbing de latencia imprime (números basura por reloj sintético — ignorar).
  - Conectividad live 25 s limpia.
- Hallazgo: `python-dotenv` faltaba en el venv recreado — instalado. **Lección**:
  recrear venv siempre desde `requirements.txt`.
- Lanzamiento manual 9:00–9:15 ET. **Un solo Ctrl-C** al cerrar (esperar
  resúmenes). Ensayo desde terminal del usuario OK; excepción de teardown de
  websockets al Ctrl-C = cosmética, arreglo post-captura.
- [x] Capturar sesión NFP; reportar métricas Hurst, cobertura AMD bajo volumen
      NFP, divergencias Live↔Replay (§10). La latencia de esa sesión se PERDIÓ
      (bug de Ctrl-C, corregido en §10); re-medición vs línea base §7 queda
      como pendiente activo para la FOMC 28–29 jul.
- [x] Revertir `SOURCE` a replay tras la captura (§10).
- [x] Teardown limpio del WebSocket (§10).

### Tarea B — AMD a 5m (después del reporte de Tarea A, por replay)
- Parámetros fijados de antemano:
  - Umbral de segmentación **derivado del timeframe**: tolerar 2× duración de
    barra, cortar >2× (elimina el hardcode de 1m de §8).
  - Ventana **60** a 5m.
  - `BarResampler` alimenta el buffer desde el stream 1m (sin suscripción aparte).
  - Ventanas 5m incompletas se **excluyen** (política §7).
- [x] **Verificación (no calibración)** replay 15-jun y 17-jun: huecos de 1 min
      desaparecen al agregar; huecos ≥180 s se reflejan coherentemente; ¿AMD
      llena ventanas de 60? → hecha y documentada en §10 (respuesta: NO en
      ninguna de las dos fechas; hipótesis del colapso de huecos falsificada).
- Rama `feature/timeframe-aware-segmentation`; merge tras reporte.

### Repo pública (2026-07-01)
- **github.com/Elorro/hurst-terminal**, MIT, creada desde local (sin historia
  previa → sin auditoría necesaria).
- `.gitignore` antes de todo `add`; `git check-ignore .env` verificado;
  duplicados de `backend/` eliminados (fuente única en raíz); `requirements.txt`
  curado y pineado.
- BITACORA y spec publicadas por decisión.
- Carpeta local renombrada `terminal-trading` → `hurst-terminal`; venv recreado.

## 10. Cierre Tarea A (Live NFP) y Tarea B (AMD a 5m) — jue 2026-07-02

### Tarea A — primera corrida Live del motor (sesión completa 9:30–15:59 ET)
- Estados (suma cuadra con lo impreso): NVDA 120 incompleto + 270 H = 390, sin
  huecos; AMD 120 + 140 H + 120 segmentación = 380.
- AMD, hallazgo fino: los 10 minutos "faltantes" SÍ tenían barra en el feed,
  pero PLANA (una sola transacción IEX) → excluidas por SessionFilter. La firma
  de la ceguera AMD-IEX es volumen insuficiente, no ausencia de barra (hoy).
- Corte único 13:27→13:30 (planas 13:28/13:29, gap 180 s). Reacumulación exacta:
  120 barras presentes 13:30–15:33 → 119 retornos (NaN) → H a las 15:34.
- **Costo de reconstrucción visto en vivo por primera vez**: a 1m/120, un hueco
  de 3 min = ~2 h de ciego (13:30→15:34). Diseñado y aceptado en §8; hoy
  cuantificado en producción. Motiva la Tarea B.
- Datapoint cobertura: 15-jun run máx 109 → 0 H; 17-jun 122 → 2 H; hoy (NFP) H
  continuo 11:30–13:27 y 15:34–15:59. **Cobertura AMD-IEX = f(volumen de sesión).**
- **Live↔Replay: divergencia cero.** Replay del propio 02-jul reproduce la
  captura exacta (faltantes, corte, estados y H idénticos).
- **Latencia: PERDIDA** — el Ctrl-C saltó los resúmenes (bug, abajo). No se
  estima. Re-medición: sesión FOMC 28–29 jul (además, caso de estrés de §7).

### Fix de cierre ordenado (main) + revert
- run_hurst.py absorbe la cancelación del Ctrl-C y vuelca ambos resúmenes ANTES
  de salir; live.py señala stop→espera→close (cancelar a secas dejaba el socket
  abierto: esa era la excepción cosmética de websockets). Motor intacto.
- Verificado: replay 17-jun idéntico a la verificación previa; Ctrl-C a mitad
  de replay imprime resúmenes parciales; smoke live 20 s sin traceback.
- `SOURCE` revertido a "replay".

### Tarea B — segmentación consciente del timeframe (rama feature/timeframe-aware-segmentation)
- Umbral derivado del timeframe: tolerar ≤2× duración de barra, cortar >2×
  (GAP_CUT_BARS=2; elimina el hardcode de 120 s). Cruce de día corta siempre.
  AMD 5m/ventana 60 vía BarResampler sobre el MISMO stream 1m; ventanas 5m
  incompletas excluidas y contadas (solo en sesión). NVDA 1m/120 intacta.
- No-regresión: NVDA idéntica (390/390 líneas) en 15-jun, 17-jun y 02-jul.
- Verificación (no calibración) 15/17-jun — coherencia 1m→5m exacta:
  - 17-jun: 24 min ausentes + 33 planas → 17 ventanas excluidas (61+17=78 ✓),
    4 gaps 600 s tolerados, 4 cortes >600 s, todos sobre huecos reales del 1m.
  - 15-jun: 11 ausentes + 34 planas → 11 excluidas (67+11=78 ✓), 5 tolerados,
    3 cortes.
  - (a) matizada: el hueco de 1 min desaparece a 5m solo si el minuto tenía
    barra plana (cuenta para completitud); la ausencia real del feed excluye la
    ventana 5m entera (política §7) — más estricto, no más laxo.
  - (b) cumplida: huecos ≥180 s → ventana incompleta y/o gap 5m, según caso.
  - (c) **dato decisorio: AMD NO llena ventana 60 a 5m en ninguna de las dos
    fechas** (corridas máx 29 y 31 de 60 → 0 H).
- Observación extra (02-jul por replay, fuera del set pactado): con volumen NFP,
  AMD 5m = 78/78 completas, 0 cortes, H continuo 14:30–15:55 — pasa por encima
  del hueco que a 1m costó 2 h. Cobertura=volumen se sostiene también a 5m.
- Observaciones registradas, NO aplicadas (§8: verificación ≠ calibración):
  60×5m = 305 min de calentamiento → aun en día perfecto, H solo en la última
  ~1.5 h de sesión; en días tranquilos, nada. "Otra ventana/timeframe se vería
  mejor" queda como observación.
- [x] Merge a main tras confirmación del reporte (confirmada 2026-07-03).

### Decisión AMD — cierre del capítulo
- **AMD-IEX declarada fuera del alcance del Hurst intradía.** Espacio de diseño
  agotado con verificación en dos timeframes: 1m/120 marginal y día-dependiente;
  5m/60 sin cobertura en días tranquilos Y ciego al evento (calentamiento 305
  min → primera H ~14:35 > anuncio 14:00); ≥15m imposible intradía (ventana ≥50
  → ≥750 min > 390 de sesión). Causa raíz: resolución del feed, no parámetros.
- Abandonar 5m/60 tras la verificación NO es calibración: la verificación
  **falsificó la hipótesis de §9** (el colapso de huecos al agregar solo aplica
  a huecos-plana; la ausencia real excluye la ventana entera).
- Camino futuro documentado: feed SIP de pago devuelve a AMD al 1m/120. NO se
  toma por anticipado; se reevalúa con evidencia de uso tras semanas NVDA-solo.
- Pipeline queda: **NVDA 1m/120 único símbolo con H.** AMD permanece para
  barras/fases futuras (watchlist de datos ≠ watchlist de Hurst en config).
- Roadmap registrado (NO construir ahora): multi-timeframe hacia ARRIBA (barras
  diarias para régimen swing — sin problema de cobertura IEX); ampliación de
  watchlist con examen de admisión por símbolo (replay sobre fechas fijadas
  de antemano, tranquila + evento, antes de confiar). Hito de validación previo
  a todo: **FOMC 28–29 jul con NVDA**.

## 11. Captura Live FOMC 2026-07-29 (NVDA 1m/120) — hito §10 cumplido

### Verificación Live↔Replay: el motor pasa el estrés
- Replay del propio 29-jul contra la captura live: **254/265 H idénticos a 3
  decimales**; las 11 diferencias son de **+0.001**, sin patrón temporal —
  correcciones tardías del histórico (el REST devuelve la barra ya revisada), no
  divergencia de motor.
- **Ventana del anuncio 36/36 exacta** (13:45–14:20 ET, cero discrepancias).
  **H a las 14:00 = 0.433 en ambas.** Justo donde importa, la captura live es
  reproducible bit a bit.
- Cumple el hito de validación de §10: el pipeline sobrevive a la sesión de
  estrés que se venía difiriendo desde §7.

### Corte de red 09:31 ET — causa raíz verificada, NO fue el gestor de sesión
- ~09:31 ET el proceso pierde el feed. **Causa raíz: DNS/upstream del ISP**,
  verificada en journal — `systemd-resolved` degradado y NetworkManager cayendo
  de `CONNECTED_SITE` a `GLOBAL` en la misma ventana; corroborado por
  `dnf-makecache` fallando exactamente igual a la misma hora (proceso ajeno al
  terminal → descarta cualquier causa interna).
- **Explícitamente NO fue swayidle/swaylock** (la hipótesis con la que se entró
  a diagnosticar) **ni el wifi local**. Registrado para no repetir el diagnóstico
  equivocado.
- Costo: **3 minutos de mercado real perdidos (09:32–09:34)**,
  **irrecuperables**: el WebSocket entrega solo lo que ocurre mientras está
  conectado y **Alpaca no hace backfill** al reconectar.
- **Huella total acotada**: primer H a las **11:35 en vez de 11:30**, y **265 H
  en vez de 270**. Nada más se degradó.
- **Convergencia inmediata por diseño**: el hueco corta el segmento (§8), el
  buffer reacumula y a partir del primer H la serie es la misma que habría sido.
  El costo de un corte es un retraso acotado, no una sesión contaminada — el
  comportamiento que §8 prometía, visto bajo evento real.

### Firma de régimen: anecdótica, coherente solo en parte con junio
- Coinciden **dos de tres patas** con el replay FOMC 17-jun (§9): antesala
  **anti-persistente** y **mínimo del día en las 14:00** (H=0.433).
- **La pata tendencial diverge**: 29-jul **80/106 min con H>0.6** contra
  **5/106 min** en 17-jun. La fase post-anuncio no se repite.
- **n=2 → anécdota, no patrón.** No se deriva de aquí ninguna regla ni umbral;
  queda como observación (§8: verificación ≠ calibración).

### Latencia bajo estrés: PERDIDA otra vez, por otra razón
- El bug de Ctrl-C de §10 está corregido, pero `LatencyLogger` **no persiste las
  muestras**: los resúmenes se imprimieron y el detalle murió con el proceso.
- Lo derivable del resumen: **mediana 0.36 s** (sana, comparable a la línea base
  §7) pero **cola un orden de magnitud peor** que esa base, con **~20 barras
  ≥1.49 s**.
- **Irrecuperable**: la distribución horaria — lo único que respondería si la
  cola se concentra en las 14:00 o está repartida, que es la pregunta real.
- **El pendiente de §7 (latencia bajo estrés vs línea base) sigue ABIERTO.** Dos
  sesiones de evento gastadas sin medirlo.

### Pendientes activos
- [ ] **Persistir las muestras de latencia a disco** (CSV por sesión, no solo
      resumen en consola) — ANTES del próximo FOMC. Sin esto la re-medición
      vuelve a perderse.
- [ ] Re-medir latencia bajo estrés en el **próximo FOMC** y comparar contra la
      línea base de §7 (mediana 0.27–0.28 / p95 0.36–0.37 / max 0.42).
- [ ] **Requisito de procedimiento revisado**: el objetivo NO es inhibir
      swayidle (hipótesis falsificada arriba) sino **detectar y sobrevivir
      cortes de red** — visibilidad del estado de conexión y del hueco que deja,
      dado que el backfill no existe.
- [ ] Decisión **no obvia**: ¿rellenar por REST los minutos perdidos tras una
      reconexión? Mezcla dos fuentes en la misma serie y toca el borde de
      entrada al buffer → **discutir contra §8**, no implementar ahora.

## 12. Protocolo de etiquetado para acumulación de evidencia (definido 2026-09-04, antes de la 1ª captura formal)

### Motivación
- Con **n=2** (FOMC 17-jun por replay, FOMC 29-jul live) hay observaciones
  sugerentes pero **no patrón** (§11). Para que "acumular evidencia" no degenere
  en coleccionar confirmaciones, se fija **de antemano** qué se mide de cada
  sesión.
- Es §8 aplicado a la observación, no al código: **verificación ≠ calibración**.
  Las ventanas y métricas se fijan **ahora**; no se eligen retroactivamente según
  lo que confirme.

### Hipótesis primaria (falsable, test binario por sesión)
- **El minuto del H mínimo global de la sesión regular (9:30–16:00 ET) cae en
  [hora_anuncio, hora_anuncio + 5 min].** Acierto/fallo por sesión, sin matices.
- Se exige **mínimo global**, no local: con mínimos locales el test se
  trivializa (siempre habría uno cerca).

### Sub-registro anti-trivialidad (obligatorio en cada sesión)
- Registrar también el **minuto del mayor salto de precio del día**, con esta
  definición operacional **fijada el 2026-09-04** (no elegible retroactivamente):
  **el minuto con el mayor |log-retorno| entre barras consecutivas de la sesión
  regular (9:30–16:00 ET)**, computado **post-hoc desde las barras crudas** — no
  desde el CSV de H/D (que no trae precio) y **sin instrumentar el motor**.
- **Por qué |log-retorno| y no rango de vela**: el H se calcula sobre
  log-retornos, así que el shock que puede mover el indicador es el log-retorno.
  Medir el salto con **la misma cantidad** que alimenta el DFA hace la
  comparación limpia; el rango de vela introduciría una métrica distinta de la
  que el indicador realmente ve.
- Si el mínimo de H **coincide siempre** con el mayor salto → el indicador solo
  sigue al shock de precio: caso **trivial**, informa la hora del anuncio, que ya
  se conocía de antemano.
- Si el mínimo cae **a veces** en un minuto sin el mayor salto → ahí hay algo que
  el precio crudo no da. Esa es la única lectura que justifica el indicador.

### Secundarias (descriptivas, SIN test binario)
- Media de H y **reparto de régimen** (minutos con H<0.45 / 0.45–0.55 / >0.55) en
  dos ventanas fijas por reloj:
  - **antesala**: [anuncio−60, anuncio]
  - **post**: [anuncio+15, anuncio+120]
- Se **observan**, no se les exige confirmar nada. La fase post-anuncio **ya
  divergió** entre jun y jul (§11: 5/106 vs 80/106 min con H>0.6): eso la
  descalifica como hipótesis y la deja como descripción.
- El post arranca en **+15 min** para no solaparse con la **rueda de prensa
  (14:30 ET)**, que es un evento distinto del comunicado.

### Reglas de registro
- **Muestra completa**: toda sesión capturada entra en la tabla, confirme o no la
  firma. Defensa explícita contra **sesgo de supervivencia**.
- **Variable de estratificación**: registrar si el evento trae **dot plot / SEP**.
  Indicio con n=2 de reacción más intensa con SEP (17-jun **con** SEP: mín
  H=0.350; 29-jul **sin** SEP: mín H=0.433). **No promediar con/sin SEP sin
  separar.**
  - Fuente del mínimo de jun, **verificada desde datos persistidos**
    (2026-09-08): `outputs/hurst_replay_2026-06-17_102904.csv` da **mín global
    H = 0.350462 exactamente a las 14:00:00 ET**. Deja de ser cifra sin fuente.
- **FOMC vs NFP/CPI = series separadas.** El FOMC sale **en sesión** (14:00 ET) y
  es testeable por la hipótesis primaria. NFP/CPI salen **pre-market (8:30 ET)**:
  invisibles al pipeline salvo por la apertura ya digerida (§9) — el anuncio ni
  siquiera cae dentro de la ventana de datos. Van como **observación secundaria
  con su propia lógica** (reacción en apertura), **NO** en la misma tabla del
  test primario.

### Techo de poder estadístico (reconocido de antemano)
- ~**8 FOMC/año**, de los cuales **4 con SEP**. Esto produce **indicios
  direccionales en meses, no prueba**. Registrar honestamente; no sobreinterpretar
  n chico.

### Próxima captura formal
- **FOMC 16-sep (con dot plot), anuncio 14:00 ET.** Primera bajo este protocolo y
  primera con SEP bajo **persistencia completa** (H/D y latencia a CSV, §11).
