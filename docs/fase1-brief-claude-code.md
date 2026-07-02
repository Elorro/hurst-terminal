# Brief para Claude Code — Fase 1: Esqueleto de datos (Terminal Nasdaq)

> Lee primero `spec-terminal-nasdaq.md` (la spec completa del proyecto) y
> `hurst_dfa.py` (existe ya; NO se toca en Fase 1). Este brief acota Fase 1
> y fija decisiones ya tomadas en sesión de arquitectura. No las reabras.

---

## 0. Objetivo de Fase 1 (y solo Fase 1)

Un backend en Python que:
1. Se conecta a datos de mercado de AMD y NVDA vía Alpaca.
2. Construye / recibe velas OHLC de 1m.
3. Las imprime por consola, de forma legible, para verificar que el flujo funciona.

**Fuera de alcance en Fase 1 (NO construir todavía):**
- Frontend / gráficos / Lightweight Charts.
- Cálculo de Hurst / DFA (la función `dfa()` existe pero NO se integra aún).
- Servidor WebSocket local hacia el frontend.
- Paper trading.
- Panel de noticias/social.

Si el código empieza a tocar cualquiera de esos, te desviaste. Para.

---

## 1. Entorno

- **Python 3.14** en un **venv** (`python3.14 -m venv .venv`). No instalar en el
  Python del sistema.
- Verificado: `alpaca-py 0.43.4` declara `Requires-Python >=3.8,<4.0` y sus
  rangos de dependencias son abiertos hacia arriba
  (`pydantic>=2.0.3,<3`, `websockets>=10.4`, `msgpack>=1.0.3,<2`). Los wheels
  `cp314` de `pydantic-core` y `aiohttp` ya existen en PyPI, así que la
  instalación NO debería compilar desde fuente. Si `msgpack` intentara
  compilar, reportarlo (es el único comodín).

### Dependencias
```
alpaca-py
numpy
pandas
python-dotenv
```
(Sin servidor WS en Fase 1.)

### Credenciales
- Se leen de un `.env` local (NO hardcodear, NO commitear). Variables:
  - `APCA_API_KEY_ID`
  - `APCA_API_SECRET_KEY`
- Son claves de **paper trading**. El feed de datos va por la misma cuenta.
- Incluir `.env.example` con las claves vacías y `.env` en `.gitignore`.

---

## 2. Decisión de arquitectura central: fuente de datos polimórfica

El backend define una **interfaz común de fuente de datos**. Dos
implementaciones intercambiables emiten barras por el MISMO canal. El resto del
pipeline (agregador, y más adelante Hurst) NO sabe ni le importa de cuál vienen.

```
        ┌──────────────┐        ┌──────────────┐
        │ ReplaySource │        │  LiveSource  │
        │ REST histór. │        │  WebSocket   │
        │ + reloj      │        │  tiempo real │
        └──────┬───────┘        └──────┬───────┘
               │   (misma interfaz: emite Bar)   │
               └──────────────┬─────────────────┘
                              ▼
                     consumidor de barras
                  (Fase 1: imprime por consola)
```

Interfaz sugerida (ajústala a tu criterio, pero mantén la simetría):
- `DataSource` con un método async que produce barras (callback o async
  generator). Cada barra es un objeto/dict OHLC normalizado:
  `{symbol, timestamp, open, high, low, close, volume}`.
- `LiveSource(DataSource)` — envuelve `StockDataStream`.
- `ReplaySource(DataSource)` — usa `StockHistoricalDataClient` +
  `StockBarsRequest`, descarga un rango histórico y lo re-emite con un "reloj"
  a velocidad configurable (1x, 10x, instantáneo).

**Por qué así:** el caso de uso principal del usuario es estudiar reacciones a
la Fed (FOMC ~14:00 ET, fechas conocidas). El replay no es solo para depurar:
es la herramienta de estudio. Y desacopla el desarrollo del horario de mercado.

**Orden de validación:** valida PRIMERO con `ReplaySource` (determinista, corre
a cualquier hora) y luego `LiveSource` cuando el mercado abra. Esto separa
"¿la fuente conecta?" de "¿el agregador agrega bien?" — no los depures juntos.

---

## 3. Modo live: A-con-B-detrás-de-flag

Para `LiveSource`, dos modos de suscripción, seleccionables por flag/config:

- **Modo A (default): suscribirse a `bars`.** Alpaca entrega la vela de 1m ya
  agregada. No construyes nada. Es lo que valida el flujo en Fase 1.
- **Modo B (detrás de flag, dejar preparado pero no es el camino por defecto):**
  suscribirse a `trades` y agregar OHLC a mano en el timeframe elegido. Es la
  responsabilidad que marca la spec §4.2, necesaria luego para timeframes no
  estándar o ver velas formándose. Implementa el esqueleto del agregador pero
  no lo actives por defecto.

El `ReplaySource` usa barras históricas directamente (equivalente al modo A).
El agregador de trades (modo B) es código separado que NO está en el camino
crítico de Fase 1.

---

## 4. Clases del SDK (verificadas)

- Live:    `from alpaca.data.live import StockDataStream`
- Histór.: `from alpaca.data.historical import StockHistoricalDataClient`
- Request: `from alpaca.data.requests import StockBarsRequest`
- Timeframe: `from alpaca.data.timeframe import TimeFrame`
- Feed: explícito `feed=DataFeed.IEX` (no asumir el default).

Watchlist inicial: `["AMD", "NVDA"]`, extensible por config.
Timeframe inicial: **1m**.

---

## 5. Límites del feed gratuito IEX (importante — no asumir)

1. **Recency / antigüedad:** el plan gratuito bloquea datos SIP *recientes*
   (<15 min). Datos >15 min son accesibles. IEX en tiempo real sí está
   disponible gratis. Para `ReplaySource` pidiendo días pasados → sin problema.
   Para datos de "hoy" → dejar margen de 15 min en el parámetro `end`.

2. **Profundidad histórica:** barras IEX disponibles desde ~mediados de 2020
   (SIP desde ~2017). Irrelevante para sesiones recientes de la Fed, pero no
   asumir profundidad infinita.

3. **A VERIFICAR en la primera corrida real:** hay reportes de usuarios del plan
   gratuito donde el histórico devolvía solo hasta ~9h desde el momento actual
   pese a los parámetros. No confirmado (¿bug? ¿config?). Si aparece al pedir
   un día pasado, reportarlo antes de seguir — no asumir que es normal.

4. **Rate limit:** ~200 llamadas/min en el plan gratuito. De sobra para Fase 1.

5. **Horario:** el feed live de barras solo fluye en horas de mercado
   (9:30–16:00 ET). Fuera de eso, NO llegan barras y NO está roto. Por eso
   `ReplaySource` es el modo de prueba fuera de horario.

---

## 6. Estructura de módulos sugerida

Coherente con spec §4 ("un módulo de datos, uno de indicadores, uno de
servidor"). En Fase 1 solo aparece el de datos:

```
backend/
  .env.example
  config.py          # watchlist, timeframe, feed, modo (A/B), velocidad replay
  sources/
    base.py          # DataSource (interfaz)
    live.py          # LiveSource (StockDataStream)
    replay.py        # ReplaySource (histórico + reloj)
  aggregator.py      # agregador OHLC de trades (modo B); esqueleto, no en camino crítico
  main.py            # arma la fuente según config e imprime barras por consola
```
(Reservar `indicators/` y `server/` para fases posteriores; no crearlos aún.)

---

## 7. Criterio de "Fase 1 terminada"

- [ ] `python main.py` con `ReplaySource` reproduce un día histórico conocido
      de AMD y NVDA e imprime velas OHLC legibles. Corre a cualquier hora.
- [ ] `python main.py` con `LiveSource` (modo A) imprime velas en vivo durante
      sesión de mercado.
- [ ] Cambiar de una fuente a otra es solo config, sin tocar el consumidor.
- [ ] Credenciales desde `.env`; nada hardcodeado; `.env` en `.gitignore`.
- [ ] Sin frontend, sin Hurst, sin WS local, sin paper trading.

---

## 8. Notas de filosofía (para no desviarse en fases siguientes)

- El Hurst es **diagnóstico de régimen**, no señal de timing. No optimizar
  umbrales para señales automáticas. (No aplica a Fase 1, pero tenlo presente
  para no construir "de más".)
- El valor del proyecto son los indicadores propios en vivo, NO reinventar el
  gráfico de velas. El gráfico base (fase posterior) es Lightweight Charts.
