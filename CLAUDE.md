# hurst-terminal — contexto para Claude

Terminal personal de régimen de mercado: exponente de Hurst rolling (vía DFA) y
dimensión fractal D = 2 − H sobre acciones del Nasdaq, con datos de Alpaca.
**Diagnóstico de régimen, NO señales de trading.** Repo pública:
github.com/Elorro/hurst-terminal (MIT).

## Documentos fuente (leer antes de tocar código)

- `docs/spec-terminal-nasdaq.md` — especificación completa: arquitectura,
  filosofía del indicador (§6), roadmap (§7) y fuera-de-alcance (§9).
- `docs/BITACORA.md` — decisiones tomadas, lecciones y pendientes con
  parámetros ya fijados. **Fuente de verdad del estado actual**: leer las
  últimas secciones antes de proponer trabajo. Este archivo solo contiene lo
  estable; el estado vive allá.
- `docs/hurst_dfa.py` — implementación de referencia de DFA, validada contra
  series sintéticas de los tres regímenes. **No modificar**: `backend/hurst.py`
  la importa y su pureza es lo que permite re-validarla.

## Arquitectura

- **Fuente polimórfica**: interfaz `DataSource` con dos implementaciones
  intercambiables — `LiveSource` (WebSocket) y `ReplaySource` (REST histórico +
  reloj) — que emiten `Bar` por el mismo canal (`stream()`, async generator).
  El consumidor no sabe de cuál viene cada barra.
- **Pipeline de Hurst**, de afuera hacia adentro: `SessionFilter` (qué barra
  cuenta: sesión regular ET, velas planas fuera) → `HurstBuffer` (ventana
  rolling de log-retornos + segmentación por contigüidad; umbral derivado del
  timeframe: tolerar hasta 2× la duración de barra, cortar >2×; cruce de día
  corta siempre) → `dfa()` pura (solo calcula sobre serie limpia 1D).
- **Dos watchlists en config, no confundirlas**: `WATCHLIST` (datos: Fase 1,
  barras, fases futuras) ≠ `HURST_WATCHLIST` (símbolos que entran al motor).
  Entrar al motor exige examen de admisión por símbolo (bitácora §10).
- Timeframes >1m se derivan localmente con `BarResampler` desde el MISMO stream
  de 1m (una sola suscripción). El resampler agrega, el buffer segmenta — no
  fusionar responsabilidades.

## Filosofía del indicador

- Hurst/D es diagnóstico de régimen, no señal de timing. Interesa verlo migrar
  en ventanas móviles; el H global es casi inútil y no hay un H "verdadero"
  único (depende de la ventana).
- **Verificación ≠ calibración**: los parámetros se fijan de antemano y el
  replay solo verifica. Pensar "con otro umbral/ventana se vería mejor" →
  parar; eso es sobreajuste.
- Preferir hueco visible a H inventado: NaN es dato de régimen (mercado
  paralizado o feed sin resolución) — verlo, no enterrarlo.

## Metodología de trabajo (obligatoria)

- Desarrollo por fases con compuertas: diseño → validación matemática →
  prototipo → testing. No avanzar de fase sin validación explícita de Luis.
- Validar primero con replay (determinista, corre a cualquier hora), luego
  live. El replay no es solo para depurar: es la herramienta de estudio.
- Toda decisión relevante se registra en la BITACORA, incluida la evidencia
  que la sustenta.

## Decisiones cerradas (no reabrir sin motivo documentado)

- **AMD está fuera del Hurst intradía vía IEX** (bitácora §10): causa raíz =
  resolución del feed, verificada a 1m y a 5m. Solo volvería con feed SIP de
  pago y evidencia de uso real. Sigue disponible en la watchlist de datos.
- El filtrado vive en el borde de entrada al buffer, nunca dentro de `dfa()`
  (bitácora §8).
- No competir con TradingView: el valor único es el Hurst/fractal en vivo;
  paridad de funciones de gráficos es tiempo perdido (bitácora §6).

## Convenciones no negociables

- Timestamp de barra Alpaca = INICIO del minuto (09:30:00 cubre 09:30–09:31).
  Sesión regular: primera barra 09:30:00, última 15:59:00 ET.
- Hora ET siempre vía `zoneinfo` (`America/New_York`), nunca offset UTC
  hardcodeado (debe sobrevivir al cambio EDT/EST).
- Ventanas incompletas se excluyen, no se rellenan.
- Cambiar replay ↔ live es solo tocar `SOURCE` en `backend/config.py`; el
  consumidor es idéntico para ambas fuentes.
- Recrear el venv siempre desde `requirements.txt` (versiones pineadas).

## Cómo correr

```bash
source .venv/bin/activate         # o el venv que exista en el repo
python backend/main.py            # Fase 1: velas por consola
python backend/run_hurst.py       # Fase 2: Hurst rolling
python backend/validate_live.py   # validación live vs replay
```

Credenciales en `backend/.env` (plantilla en `.env.example`). Nunca commitear
`.env`; verificar con `git check-ignore backend/.env`.

## Estado actual

Vive en `docs/BITACORA.md` — leer las últimas secciones.
