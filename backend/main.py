"""Punto de entrada de Fase 1.

Arma la fuente de datos según config e imprime las velas por consola. El
consumidor es idéntico para replay y live: cambiar de uno a otro es solo tocar
SOURCE en config.py.
"""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

import config
from sources import DataSource, LiveSource, ReplaySource

_ET = ZoneInfo("America/New_York")


def build_source() -> DataSource:
    if config.SOURCE == "replay":
        return ReplaySource(
            api_key=config.APCA_API_KEY_ID,
            secret_key=config.APCA_API_SECRET_KEY,
            symbols=config.WATCHLIST,
            day=config.REPLAY_DATE,
            feed=config.FEED,
            speed=config.REPLAY_SPEED,
            recency_margin_minutes=config.RECENCY_MARGIN_MINUTES,
        )
    if config.SOURCE == "live":
        return LiveSource(
            api_key=config.APCA_API_KEY_ID,
            secret_key=config.APCA_API_SECRET_KEY,
            symbols=config.WATCHLIST,
            feed=config.FEED,
            mode=config.LIVE_MODE,
        )
    raise ValueError(f"SOURCE inválido: {config.SOURCE!r} (usa 'replay' o 'live').")


def print_header() -> None:
    print(
        f"Fuente: {config.SOURCE}  |  watchlist: {config.WATCHLIST}  |  "
        f"timeframe: {config.TIMEFRAME}  |  feed: {config.FEED}"
    )
    if config.SOURCE == "replay":
        print(f"Replay del día {config.REPLAY_DATE}  (velocidad: {config.REPLAY_SPEED}x)")
    else:
        print(f"Live modo {config.LIVE_MODE} (solo fluye en horario de mercado ET)")
    print("-" * 78)
    print(
        f"{'símbolo':<7} {'hora ET':<19} "
        f"{'open':>9} {'high':>9} {'low':>9} {'close':>9} {'volumen':>12}"
    )
    print("-" * 78)


def print_bar(bar) -> None:
    ts_et = bar.timestamp.astimezone(_ET).strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"{bar.symbol:<7} {ts_et:<19} "
        f"{bar.open:>9.2f} {bar.high:>9.2f} {bar.low:>9.2f} "
        f"{bar.close:>9.2f} {bar.volume:>12,.0f}"
    )


async def run() -> None:
    source = build_source()
    print_header()
    count = 0
    async for bar in source.stream():
        print_bar(bar)
        count += 1
    print("-" * 78)
    print(f"Total de velas emitidas: {count}")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nDetenido por el usuario.")
    except RuntimeError as e:
        raise SystemExit(f"\n[error] {e}")
