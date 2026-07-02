"""Validación de LiveSource (modo A) en sesión abierta.

- Suscribe a barras de 1m de la watchlist (modo A; sin construir nada a mano).
- Deriva 5m por agregación local (BarResampler) — NO una suscripción aparte.
- Registra latencia por barra de 1m (LatencyLogger).
- Al terminar (duración agotada o Ctrl-C):
    * imprime el resumen de latencia (min/mediana/p95/max por símbolo);
    * cruza la 5m derivada contra la 5m histórica de Alpaca como prueba del
      agregador, solo en ventanas completas y con end <= ahora - margen recency.

Solo tiene sentido en horario de mercado (lun-vie 9:30-16:00 ET). Fuera de eso
no llegan barras y el resumen saldrá vacío (no está roto; ver brief §5.5).

Uso:  python validate_live.py [minutos]   (por defecto 25)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

import config
from aggregator import BarResampler
from latency_logger import LatencyLogger
from sources import Bar, LiveSource

_ET = ZoneInfo("America/New_York")
_PRICE_TOL = 0.01   # tolerancia de precio (centavos) al cruzar
_VOL_TOL = 1.0      # tolerancia de volumen


def _fmt(b: Bar) -> str:
    ts = b.timestamp.astimezone(_ET).strftime("%H:%M")
    return (
        f"O={b.open:.2f} H={b.high:.2f} L={b.low:.2f} "
        f"C={b.close:.2f} V={b.volume:,.0f} @{ts}"
    )


async def capture(duration_s: float):
    """Captura barras de 1m en vivo durante `duration_s`. Devuelve el logger de
    latencia, el resampler y las 5m derivadas {symbol: {window_ts: Bar}}."""
    source = LiveSource(
        api_key=config.APCA_API_KEY_ID,
        secret_key=config.APCA_API_SECRET_KEY,
        symbols=config.WATCHLIST,
        feed=config.FEED,
        mode="A",
    )
    logger = LatencyLogger(period_seconds=60.0, echo=True)
    resampler = BarResampler(minutes=5)
    derived_5m: dict[str, dict[datetime, Bar]] = {}

    print(
        f"Live modo A | watchlist {config.WATCHLIST} | feed {config.FEED} | "
        f"capturando {duration_s/60:.0f} min ...",
        flush=True,
    )
    print("Esperando primera barra (puede tardar hasta ~1 min + latencia)...\n", flush=True)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + duration_s
    agen = source.stream()
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                bar = await asyncio.wait_for(agen.__anext__(), timeout=remaining)
            except (asyncio.TimeoutError, StopAsyncIteration):
                break
            recv_ts = datetime.now(_ET)

            s = logger.record(bar.symbol, bar.timestamp, recv_ts)
            print(f"1m  {bar.symbol:<5} {_fmt(bar)}  (lat {s.latency_s:+.2f}s)", flush=True)

            closed = resampler.add_bar(bar)
            if closed is not None:
                derived_5m.setdefault(closed.symbol, {})[closed.timestamp] = closed
                print(f"  -> 5m DERIVADA {closed.symbol:<5} {_fmt(closed)}", flush=True)
    finally:
        await agen.aclose()

    # cerrar ventanas de 5m a medio formar (no se cruzan, pero se reportan)
    for closed in resampler.flush():
        derived_5m.setdefault(closed.symbol, {})[closed.timestamp] = closed

    return logger, resampler, derived_5m


def cross_check(resampler: BarResampler, derived_5m: dict[str, dict[datetime, Bar]]):
    """Compara la 5m derivada contra la 5m de Alpaca en ventanas completas y
    suficientemente antiguas (margen de recency del feed gratuito)."""
    print("\n=== Cross-check 5m derivada vs Alpaca (prueba del agregador) ===")
    if not derived_5m:
        print("(no se derivó ninguna vela de 5m)")
        return

    margin = timedelta(minutes=config.RECENCY_MARGIN_MINUTES)
    cutoff = datetime.now(timezone.utc) - margin  # ventana debe CERRAR antes de esto

    # ventanas elegibles: completas (cierran antes del cutoff). Si ninguna es aún
    # suficientemente antigua, no pedimos nada (evita un rango start>end inválido).
    eligible = [
        (sym, w)
        for sym, wins in derived_5m.items()
        for w in wins
        if (w + timedelta(minutes=5)).astimezone(timezone.utc) <= cutoff
    ]
    if not eligible:
        print(
            "(ninguna ventana de 5m es aún suficientemente antigua para cruzar; "
            f"se necesita end <= ahora - {config.RECENCY_MARGIN_MINUTES} min)"
        )
        return

    start = min(w for _, w in eligible).astimezone(timezone.utc)

    client = StockHistoricalDataClient(config.APCA_API_KEY_ID, config.APCA_API_SECRET_KEY)
    req = StockBarsRequest(
        symbol_or_symbols=config.WATCHLIST,
        timeframe=TimeFrame(5, TimeFrameUnit.Minute),
        start=start,
        end=cutoff,
        feed=DataFeed(config.FEED),
    )
    alp = client.get_stock_bars(req)
    # index Alpaca: {(symbol, window_utc): bar}
    alp_idx = {
        (b.symbol, b.timestamp.astimezone(timezone.utc)): b
        for bars in alp.data.values() for b in bars
    }

    print(f"{'símbolo':<7} {'ventana ET':<8} {'#1m':>4} {'resultado':<9} detalle")
    total = ok = 0
    for sym in sorted(derived_5m):
        for window in sorted(derived_5m[sym]):
            window_end = window + timedelta(minutes=5)
            if window_end.astimezone(timezone.utc) > cutoff:
                continue  # demasiado reciente para cruzar de forma fiable
            w_et = window.astimezone(_ET).strftime("%H:%M")
            n1m = resampler.last_count.get((sym, window), 0)
            if n1m < 5:
                print(
                    f"{sym:<7} {w_et:<8} {n1m:>4} {'PARCIAL':<9} "
                    f"solo {n1m}/5 velas de 1m (IEX sin barra en algún minuto)"
                )
                continue
            d = derived_5m[sym][window]
            key = (sym, window.astimezone(timezone.utc))
            a = alp_idx.get(key)
            total += 1
            if a is None:
                print(f"{sym:<7} {w_et:<8} {n1m:>4} {'SIN DATO':<9} Alpaca no devolvió esa 5m")
                continue
            diffs = []
            for field in ("open", "high", "low", "close"):
                if abs(getattr(d, field) - float(getattr(a, field))) > _PRICE_TOL:
                    diffs.append(f"{field} {getattr(d, field):.2f}!={float(getattr(a, field)):.2f}")
            if abs(d.volume - float(a.volume)) > _VOL_TOL:
                diffs.append(f"vol {d.volume:.0f}!={float(a.volume):.0f}")
            if diffs:
                print(f"{sym:<7} {w_et:<8} {n1m:>4} {'DIFF':<9} {'; '.join(diffs)}")
            else:
                ok += 1
                print(f"{sym:<7} {w_et:<8} {n1m:>4} {'OK':<9} OHLCV coincide")
    print(f"\nVentanas completas cruzadas: {ok}/{total} coinciden.")


async def main():
    minutes = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    try:
        logger, resampler, derived_5m = await capture(minutes * 60)
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
        return
    logger.print_summary()
    cross_check(resampler, derived_5m)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    except RuntimeError as e:
        raise SystemExit(f"\n[error] {e}")
