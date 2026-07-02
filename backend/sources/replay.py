"""ReplaySource: descarga un rango histórico y lo re-emite con un reloj.

No es solo para depurar: es la herramienta de estudio (reacciones a la Fed,
FOMC ~14:00 ET en fechas conocidas) y desacopla el desarrollo del horario de
mercado. Equivalente al modo A de live, pero sobre barras históricas.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from typing import AsyncIterator, Iterable

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from .base import Bar, DataSource

# Timeframe inicial fijo de Fase 1 (1m). Si se generaliza, mapear desde config.
_ONE_MINUTE = TimeFrame(1, TimeFrameUnit.Minute)


class ReplaySource(DataSource):
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        symbols: Iterable[str],
        day: str,
        feed: str = "iex",
        speed: float = 0.0,
        recency_margin_minutes: int = 16,
    ):
        if not api_key or not secret_key:
            raise RuntimeError(
                "Faltan credenciales Alpaca. Rellena backend/.env "
                "(APCA_API_KEY_ID / APCA_API_SECRET_KEY)."
            )
        self._client = StockHistoricalDataClient(api_key, secret_key)
        self._symbols = list(symbols)
        self._day = day
        self._feed = DataFeed(feed)
        self._speed = speed
        self._recency_margin = timedelta(minutes=recency_margin_minutes)

    def _day_bounds(self) -> tuple[datetime, datetime]:
        """Rango UTC del día pedido. Recorta `end` si roza la ventana de 15 min
        bloqueada por el feed gratuito IEX."""
        d = datetime.strptime(self._day, "%Y-%m-%d").date()
        start = datetime.combine(d, time.min, tzinfo=timezone.utc)
        end = datetime.combine(d, time.max, tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - self._recency_margin
        if end > cutoff:
            end = cutoff
        return start, end

    async def stream(self) -> AsyncIterator[Bar]:
        start, end = self._day_bounds()
        req = StockBarsRequest(
            symbol_or_symbols=self._symbols,
            timeframe=_ONE_MINUTE,
            start=start,
            end=end,
            feed=self._feed,
        )
        # La descarga REST es bloqueante; la sacamos del event loop.
        barset = await asyncio.to_thread(self._client.get_stock_bars, req)

        # barset.data: {symbol: [Bar, ...]}. Mezclamos por timestamp para emitir
        # en orden cronológico real (como llegarían en vivo), no símbolo a símbolo.
        merged: list = []
        for symbol_bars in barset.data.values():
            merged.extend(symbol_bars)
        merged.sort(key=lambda b: b.timestamp)

        if not merged:
            print(
                f"[replay] Sin barras para {self._symbols} en {self._day}. "
                "¿Día festivo/fin de semana, o el feed gratuito limitó la "
                "profundidad histórica? (ver brief §5.3)."
            )
            return

        prev_ts = None
        for ab in merged:
            if self._speed > 0 and prev_ts is not None:
                gap = (ab.timestamp - prev_ts).total_seconds()
                if gap > 0:
                    await asyncio.sleep(gap / self._speed)
            prev_ts = ab.timestamp
            yield Bar.from_alpaca(ab)
