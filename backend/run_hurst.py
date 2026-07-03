"""Runner de Fase 2: Hurst rolling en vivo.

Consume barras del `DataSource` (replay o live, según config) y por cada vela
cerrada imprime {símbolo, ts, H, D} + estado. Al terminar (replay) o al cortar
(live), vuelca las métricas de exclusión/anulación por símbolo.

Cambiar de fuente es solo tocar SOURCE en config.py; este consumidor no cambia.
"""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from aggregator import BarResampler
from hurst import (
    COMPUTED,
    EXCLUDED_FLAT,
    EXCLUDED_OUT_OF_SESSION,
    NAN_INCOMPLETE,
    NAN_SEGMENTATION,
    SESSION_CLOSE,
    SESSION_OPEN,
    HurstEngine,
)
from latency_logger import LatencyLogger
from main import build_source

_ET = ZoneInfo("America/New_York")


def print_header() -> None:
    per_symbol = "  ".join(
        f"{s} {config.BAR_MINUTES.get(s, 1)}m/ventana "
        f"{config.HURST_WINDOWS.get(s, config.HURST_WINDOW)}"
        for s in config.WATCHLIST
    )
    print(
        f"Fuente: {config.SOURCE}  |  watchlist: {config.WATCHLIST}  |  "
        f"feed: {config.FEED}"
    )
    print(f"Timeframe/ventana: {per_symbol}  |  corte de segmento: gap > 2x barra")
    if config.SOURCE == "replay":
        print(f"Replay del día {config.REPLAY_DATE}  (velocidad: {config.REPLAY_SPEED}x)")
    else:
        print(f"Live modo {config.LIVE_MODE} (solo fluye en horario de mercado ET)")
    print("-" * 70)
    print(f"{'símbolo':<7} {'hora ET':<19} {'H':>8} {'D':>8}  estado")
    print("-" * 70)


def _fmt(x: float) -> str:
    return " nan" if math.isnan(x) else f"{x:8.3f}"


def print_result(res) -> None:
    ts_et = res.timestamp.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{res.symbol:<7} {ts_et:<19} {_fmt(res.H)} {_fmt(res.D)}  {res.status}")


def print_latency_summary(logger: LatencyLogger) -> None:
    # Solo informativo en replay (reloj sintético; los números no son latencia
    # real). En live mide recv_ts - (bar_ts + 60s): retardo de entrega del feed.
    logger.print_summary()


def print_summary(engine: HurstEngine, incomplete_windows: Counter | None = None) -> None:
    print("-" * 70)
    print("Métricas de observabilidad por símbolo (régimen, no sesgo):")
    labels = [
        (EXCLUDED_OUT_OF_SESSION, "excluidas (fuera de sesión)"),
        (EXCLUDED_FLAT, "excluidas (velas planas)"),
        (NAN_INCOMPLETE, "NaN (buffer incompleto)"),
        (NAN_SEGMENTATION, "NaN (segmentación)"),
        (COMPUTED, "H calculado"),
    ]
    for sym, counts in engine.summary().items():
        print(f"  {sym}:")
        for key, text in labels:
            print(f"    {text:<32} {counts.get(key, 0):>6}")
        if incomplete_windows and sym in config.BAR_MINUTES:
            m = config.BAR_MINUTES[sym]
            print(
                f"    {f'ventanas {m}m incompletas excluidas':<32} "
                f"{incomplete_windows.get(sym, 0):>6}"
            )


async def run() -> None:
    source = build_source()
    engine = HurstEngine(
        config.WATCHLIST,
        window=config.HURST_WINDOW,
        windows=config.HURST_WINDOWS,
        bar_seconds={s: m * 60 for s, m in config.BAR_MINUTES.items()},
    )
    logger = LatencyLogger(echo=False)  # latencia de entrega por barra de 1m

    # Timeframes >1m se derivan localmente del MISMO stream de 1m (una sola
    # suscripción). Separación de responsabilidades: el resampler agrega, el
    # buffer segmenta. Una ventana con menos de `m` barras de 1m se excluye
    # (política §7) y se cuenta aparte: el motor ni la ve.
    resamplers = {
        s: (BarResampler(m), m) for s, m in config.BAR_MINUTES.items() if m > 1
    }
    incomplete_windows: Counter = Counter()

    def admit(closed, resampler: BarResampler, minutes: int):
        """Ventana agregada recién cerrada -> barra para el motor, o None si se
        excluye por incompleta. Solo cuentan en la métrica las ventanas DENTRO
        de sesión: una de pre/post-market incompleta no es ceguera del motor
        (la habría descartado igual el filtro de sesión)."""
        if resampler.last_count[(closed.symbol, closed.timestamp)] < minutes:
            t_et = closed.timestamp.astimezone(_ET).time()
            if SESSION_OPEN <= t_et < SESSION_CLOSE:
                incomplete_windows[closed.symbol] += 1
            return None
        return closed

    def to_engine_bar(bar):
        """La barra de 1m tal cual, o la vela agregada del símbolo (None si su
        ventana sigue abierta o se excluyó por incompleta)."""
        entry = resamplers.get(bar.symbol)
        if entry is None:
            return bar
        resampler, minutes = entry
        closed = resampler.add_bar(bar)
        return None if closed is None else admit(closed, resampler, minutes)

    print_header()
    if config.SOURCE == "live":
        # Distingue la espera silenciosa pre-9:30 (normal: el feed solo fluye en
        # sesión) de un cuelgue real. La suscripción ya se emitió al iniciar stream().
        print(
            f"Suscrito a {config.WATCHLIST} vía WebSocket (modo {config.LIVE_MODE}). "
            "Fuera de 9:30–16:00 ET no fluyen barras: el silencio es normal, no "
            "un cuelgue. Esperando primera barra...",
            flush=True,
        )
    try:
        async for bar in source.stream():
            # recv_ts lo antes posible tras recibir la barra (latencia de entrega).
            logger.record(bar.symbol, bar.timestamp, datetime.now(_ET))
            bar_in = to_engine_bar(bar)
            if bar_in is None:
                continue
            res = engine.on_bar(bar_in)
            if res is not None:
                print_result(res)
    except asyncio.CancelledError:
        # Ctrl-C: asyncio.run() convierte el SIGINT en cancelación de esta tarea.
        # Absorberla aquí (en vez de dejarla llegar al handler de __main__)
        # garantiza que los resúmenes en memoria se vuelquen ANTES de salir.
        # El teardown del WebSocket ya corrió: el finally de stream() se ejecuta
        # mientras la cancelación se propaga por el async-for.
        print("\nDetenido por el usuario. Volcando resúmenes parciales...")
    # Cierra las ventanas agregadas en construcción (la última de la sesión solo
    # se emite aquí; en un corte a mitad de ventana, `admit` la excluye).
    for resampler, minutes in resamplers.values():
        for closed in resampler.flush():
            bar_in = admit(closed, resampler, minutes)
            if bar_in is None:
                continue
            res = engine.on_bar(bar_in)
            if res is not None:
                print_result(res)
    print_summary(engine, incomplete_windows)
    print_latency_summary(logger)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    except RuntimeError as e:
        raise SystemExit(f"\n[error] {e}")
