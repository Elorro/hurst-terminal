# Bitácora de sesión — Terminal Nasdaq

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

- [ ] **Verificar Live en vivo**: que `LiveSource` (modo A) imprima velas en
      sesión.
- [ ] **Medir latencia de cierre de vela**: que la barra del minuto X aparezca
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
- [ ] `SessionFilter` (capas sesión + velas planas) en el borde de entrada.
- [ ] Buffer rolling + segmentación por contigüidad (gap > 2 min, H=NaN sin
      segmento suficiente).
- [ ] Logging de barras excluidas y ventanas anuladas por sesión.
- [ ] Mantener `dfa()` pura; reutilizar la de `hurst_dfa.py` sin tocar.
- [ ] Verificación (no calibración) vía replay de fecha FOMC pasada — elegir fecha.

### Ideas futuras registradas (NO construir ahora)
- Otras lentes de régimen que encajan con la filosofía diagnóstica: **change-point
  detection** (pareja natural del Hurst para el caso Fed: régimen + momento del
  cambio) y **HMM** (formaliza con probabilidad lo que ahora se hace con umbral).
  Ambas diagnósticas, no gatillos.
- Panel de noticias/social en tiempo real: fase muy posterior, base sería el
  endpoint de noticias gratuito de Alpaca. Fuera de alcance actual.
