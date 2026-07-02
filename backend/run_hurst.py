"""Runner de Fase 2: Hurst rolling en vivo.

Consume barras del `DataSource` (replay o live, según config) y por cada vela
cerrada imprime {símbolo, ts, H, D} + estado. Al terminar (replay) o al cortar
(live), vuelca las métricas de exclusión/anulación por símbolo.

Cambiar de fuente es solo tocar SOURCE en config.py; este consumidor no cambia.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from hurst import (
    COMPUTED,
    EXCLUDED_FLAT,
    EXCLUDED_OUT_OF_SESSION,
    NAN_INCOMPLETE,
    NAN_SEGMENTATION,
    HurstEngine,
)
from latency_logger import LatencyLogger
from main import build_source

_ET = ZoneInfo("America/New_York")


def print_header() -> None:
    print(
        f"Fuente: {config.SOURCE}  |  watchlist: {config.WATCHLIST}  |  "
        f"ventana Hurst: {config.HURST_WINDOW}  |  feed: {config.FEED}"
    )
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


def print_summary(engine: HurstEngine) -> None:
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


async def run() -> None:
    source = build_source()
    engine = HurstEngine(config.WATCHLIST, window=config.HURST_WINDOW)
    logger = LatencyLogger(echo=False)  # latencia de entrega por barra de 1m
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
    async for bar in source.stream():
        # recv_ts lo antes posible tras recibir la barra (latencia de entrega).
        logger.record(bar.symbol, bar.timestamp, datetime.now(_ET))
        res = engine.on_bar(bar)
        if res is not None:
            print_result(res)
    print_summary(engine)
    print_latency_summary(logger)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    except RuntimeError as e:
        raise SystemExit(f"\n[error] {e}")
