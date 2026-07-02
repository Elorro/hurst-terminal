# Especificación técnica — Terminal personal de análisis Nasdaq

> Documento para entregar a Claude Code como punto de partida del proyecto.
> Perfil: aplicación de **un solo usuario**, uso personal, análisis y paper trading.
> No es un broker ni un producto multiusuario.

---

## 1. Qué es esto (y qué NO es)

**Es:** un dashboard/terminal personal que se conecta a datos de mercado de EE.UU.
en tiempo real, dibuja gráficos de velas tipo TradingView, y añade indicadores
propios — en particular el exponente de Hurst y la dimensión fractal — calculados
en vivo sobre el flujo de precios.

**No es:**
- Un broker (no custodia dinero, no requiere licencias FINRA/SEC).
- Un sistema de alta frecuencia (la latencia de cientos de ms es irrelevante aquí).
- Un producto para varios usuarios (sin auth compleja, sin escalado de servidores).

**Decisión de diseño central:** el valor único frente a TradingView son los
**indicadores propios corriendo en vivo** (Hurst/fractal). El gráfico de velas base
NO debe reinventarse: usar una librería existente. Si el proyecto termina
reconstruyendo TradingView, se desvió del objetivo.

---

## 2. Fuente de datos: Alpaca (plan gratuito para empezar)

**Decisión tomada:** Alpaca Markets, tier gratuito.

Razones:
- Plan gratuito: ~200 llamadas/min (vs. 5/min de Polygon gratuito).
- WebSocket en tiempo real incluido en el plan gratuito (barras, quotes, trades).
- Históricos incluidos para backtesting del Hurst.
- Cuenta de **paper trading con API** → permite ejecutar operaciones simuladas
  desde la propia app, no solo visualizarlas.
- Es la misma infraestructura que Binance usa por debajo para su producto de
  acciones de EE.UU., lo que habla de su fiabilidad.

**Limitación conocida y aceptada:** el feed gratuito usa datos de IEX (una porción
del volumen), no el SIP consolidado completo. Para análisis de Hurst y gráficos de
swing es suficiente. El upgrade al feed consolidado existe si algún día se necesita.

**Requisito de registro:** aceptar el acuerdo de "non-professional subscriber" para
datos en tiempo real. Para uso personal aplica sin problema.

**Descartado explícitamente:** acciones tokenizadas (Binance bStocks / Kraken
xStocks). Su precio lo mantienen market makers y oráculos, diverge del Nasdaq real
fuera de horario y tiene liquidez delgada. Medir Hurst sobre el token mediría la
rugosidad del mercado tokenizado, no la del Nasdaq. NO usar como fuente de datos.

**Alternativas de upgrade (no para el inicio):**
- Polygon.io / "Massive": latencia <10ms, datos institucionales. Caro y con free
  tier restrictivo. Solo si el proyecto crece y necesita el feed consolidado.
- Finnhub: ~100ms, free tier generoso, indicadores integrados. Plan B razonable.

---

## 3. Arquitectura

```
   Alpaca WebSocket (tiempo real)
            │  ticks / barras
            ▼
   ┌─────────────────────┐
   │   BACKEND (Python)  │
   │  - cliente WS Alpaca│
   │  - agregador OHLC   │   construye velas desde ticks
   │  - cálculo Hurst    │   dfa() en ventana móvil
   │  - servidor WS local│   reenvía al frontend
   └─────────────────────┘
            │  WebSocket local (velas + H + D)
            ▼
   ┌─────────────────────┐
   │  FRONTEND (browser) │
   │  - Lightweight      │   gráfico de velas
   │    Charts (velas)   │
   │  - paneles Hurst/D  │   subgráficos debajo
   └─────────────────────┘
```

El patrón WebSocket backend↔frontend es idéntico al que el usuario ya implementó
en su proyecto de arbitraje de BTC. La diferencia es la fuente (Alpaca en vez de
exchange cripto).

---

## 4. Backend (Python)

### Responsabilidades
1. **Conexión Alpaca:** cliente WebSocket usando el SDK oficial `alpaca-py`.
   Suscribirse a barras (bars) y/o trades de los símbolos del watchlist.
   Watchlist inicial: **AMD, NVDA** (núcleo del usuario), extensible.
2. **Agregación OHLC:** si se reciben trades, agregarlos en velas del timeframe
   elegido (1m, 5m, etc.). Si Alpaca ya entrega barras, usarlas directo.
3. **Cálculo de Hurst en vivo:** mantener un buffer rolling de log-retornos por
   símbolo. Cada vez que cierra una vela, recalcular H sobre la ventana (p. ej.
   120 barras) usando DFA. Derivar D = 2 − H.
   → Reutilizar la función `dfa()` del script `hurst_dfa.py` ya existente.
4. **Servidor WebSocket local:** exponer un WS (p. ej. con `websockets` o FastAPI)
   que empuje al frontend: { símbolo, vela OHLC, timestamp, H, D }.
5. **(Opcional) Paper trading:** endpoints REST que envuelvan la API de paper
   trading de Alpaca (submit order, list positions, list orders), para ejecutar
   y revisar operaciones simuladas desde la app.

### Notas de implementación del Hurst en vivo
- H se mueve lento: recalcular solo al cierre de vela, no en cada tick.
- El tamaño de ventana es un parámetro, no un valor fijo. Exponerlo configurable.
- DFA necesita un mínimo de datos (≥ ~50 puntos). Mientras el buffer se llena,
  marcar H como no disponible en vez de devolver ruido.
- No optimizar umbrales de H para generar señales de compra/venta. El Hurst es
  una **capa de contexto de régimen**, no un gatillo de entrada. (Ver sección 6.)

### Stack sugerido
- `alpaca-py` (cliente oficial)
- `numpy`, `pandas` (cálculo)
- `fastapi` + `uvicorn` o `websockets` (servidor local)
- Estructura: un módulo de datos, un módulo de indicadores (importa dfa), un
  módulo de servidor.

---

## 5. Frontend

### Gráfico base
- **TradingView Lightweight Charts** (gratuito, open source, es el motor de
  gráficos de la propia TradingView). NO reconstruir un motor de velas a mano.
- Velas en el panel principal, alimentadas por el WS local.

### Paneles de indicadores propios (lo que hace único al proyecto)
- Subpanel **Hurst (H):** línea con referencia en 0.5. Zona verde cuando H>0.5
  (régimen de tendencia / persistente), zona roja cuando H<0.5 (reversión /
  anti-persistente).
- Subpanel **Dimensión fractal (D = 2 − H):** referencia en 1.5. Sube hacia 2
  cuando la curva es más rugosa.
- Ambos comparten el eje temporal con el gráfico de velas.

### Interacción mínima
- Selector de símbolo (AMD / NVDA / añadir).
- Selector de timeframe.
- Control del tamaño de ventana del Hurst.

---

## 6. Filosofía de uso del indicador (importante, no omitir)

El Hurst/dimensión fractal en este proyecto es **diagnóstico de régimen**, no señal
de timing. Esto debe reflejarse en la UI y en cómo se presenta:

- H alto (>0.5) → el activo está en modo tendencia → las entradas en pullback con
  expectativa de continuación tienen contexto favorable.
- H bajo (<0.5) → modo reversión → "entrar en la caída esperando rebote" es más
  coherente que perseguir tendencia.
- H ≈ 0.5 → paseo aleatorio, sin memoria explotable.

Advertencias que el diseño debe respetar:
- H global de una serie es casi inútil; lo valioso es verlo **migrar** en ventanas
  móviles. (Demostrado: una serie con 3 regímenes claros dio H global ≈ 0.5.)
- En datos reales la señal es más sucia que en datos sintéticos.
- El valor de H depende del tamaño de ventana — no hay un H "verdadero" único.
- **No** convertir esto en señales automáticas de compra/venta optimizando
  umbrales: es el camino al sobreajuste (mismo problema que la cointegración en
  pares que el usuario ya descartó en vivo).

Uso recomendado: capa de contexto + etiquetado de régimen en el trading journal,
para revisar post-hoc si los trades de continuación funcionan mejor con H alto.

---

## 7. Roadmap sugerido (para Claude Code)

**Fase 1 — Esqueleto de datos.**
Backend que conecta a Alpaca (datos demo/diferidos primero, sin pagar),
construye velas y las imprime. Verificar el flujo antes de tocar el frontend.

**Fase 2 — Hurst en vivo.**
Integrar el cálculo DFA rolling sobre el flujo. Validar contra el script
`hurst_dfa.py` con datos históricos conocidos.

**Fase 3 — Servidor + frontend.**
WS local + Lightweight Charts con velas. Conectar el flujo.

**Fase 4 — Paneles fractales.**
Subgráficos de H y D sincronizados con las velas.

**Fase 5 (opcional) — Paper trading.**
Envolver la API de paper trading de Alpaca para ejecutar/revisar operaciones.

---

## 8. Lo que hay que tener a mano antes de empezar

- Cuenta Alpaca (gratuita) + API key/secret de paper trading.
- Python 3.10+.
- El script `hurst_dfa.py` (ya existe) como base del módulo de indicadores.
- Decisión de timeframe inicial (sugerido: velas de 1m o 5m para ver el Hurst
  moverse en una sesión).

---

## 9. Fuera de alcance en esta etapa (no construir ahora)

Estas ideas están registradas para el futuro, pero **NO** forman parte del proyecto
actual. Claude Code no debe implementarlas todavía. El foco de esta etapa es
exclusivamente: datos en vivo (Alpaca) → velas → Hurst/dimensión fractal → gráfico.

- **Panel de información en tiempo real** (noticias / calendario macro / señal
  social). Pensado como fase posterior, una vez que el núcleo de gráficos+Hurst
  funcione y esté validado. Cuando se aborde, la base sería el endpoint de
  noticias que Alpaca ya incluye en el plan gratuito (sin costo adicional),
  posiblemente complementado con calendario económico. Otras fuentes evaluadas
  (FMP, LunarCrush) requieren suscripción de pago y por ahora se descartan por
  costo. Nimble queda como opción de extracción puntual solo para fuentes sin API.
  Nota de diseño para cuando llegue el momento: priorizar **curaduría sobre
  volumen** (destacar eventos de alto impacto y picos anómalos, no un chorro
  continuo de titulares que invite a reaccionar a ruido).

- **Capa de contexto macro vía agente de navegador / scraping** (calendario Fed,
  comunicados FOMC desde páginas sin API). Auxiliar y opcional. Solo recurrir a
  scraping cuando el dato no exista por API.

---

## Aviso

Esto es una herramienta de análisis y paper trading. No es asesoría de inversión.
La decisión de arriesgar capital real es siempre del usuario, y conviene validar
el comportamiento del indicador en vivo antes de confiar en él para nada.
