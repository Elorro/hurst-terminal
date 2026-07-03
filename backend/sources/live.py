"""LiveSource: barras en tiempo real vía WebSocket de Alpaca.

Modo A (default): suscripción a `bars` -> Alpaca entrega la vela de 1m ya
agregada; no construimos nada. Es lo que valida el flujo en Fase 1.

Modo B (preparado, no por defecto): suscripción a `trades` + agregador OHLC a
mano (aggregator.py). Queda cableado pero NO es el camino crítico de Fase 1.

Nota: el feed live de barras solo fluye en horario de mercado (9:30-16:00 ET).
Fuera de eso no llegan barras y NO está roto (brief §5.5).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Iterable

from alpaca.data.enums import DataFeed
from alpaca.data.live import StockDataStream

from .base import Bar, DataSource


class LiveSource(DataSource):
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        symbols: Iterable[str],
        feed: str = "iex",
        mode: str = "A",
    ):
        if not api_key or not secret_key:
            raise RuntimeError(
                "Faltan credenciales Alpaca. Rellena backend/.env "
                "(APCA_API_KEY_ID / APCA_API_SECRET_KEY)."
            )
        if mode not in ("A", "B"):
            raise ValueError(f"LIVE_MODE inválido: {mode!r} (usa 'A' o 'B').")
        self._symbols = list(symbols)
        self._mode = mode
        self._stream = StockDataStream(api_key, secret_key, feed=DataFeed(feed))

    async def stream(self) -> AsyncIterator[Bar]:
        queue: asyncio.Queue[Bar] = asyncio.Queue()

        async def on_bar(alpaca_bar):
            await queue.put(Bar.from_alpaca(alpaca_bar))

        if self._mode == "A":
            self._stream.subscribe_bars(on_bar, *self._symbols)
        else:
            # Modo B: aquí se suscribiría a trades y se alimentaría el
            # aggregator. Esqueleto fuera del camino crítico de Fase 1.
            from aggregator import OHLCAggregator  # import perezoso

            agg = OHLCAggregator()

            async def on_trade(trade):
                bar = agg.add_trade(trade)
                if bar is not None:
                    await queue.put(bar)

            self._stream.subscribe_trades(on_trade, *self._symbols)

        # `_run_forever` es la corrutina interna del SDK (run() haría asyncio.run,
        # que no se puede anidar). La corremos como tarea y puenteamos por la cola.
        runner = asyncio.create_task(self._stream._run_forever())
        try:
            while True:
                yield await queue.get()
        finally:
            # Cierre ordenado: primero la señal de stop, para que el loop del SDK
            # cierre el WebSocket por su camino normal (_consume ve la señal y
            # llama close()). Cancelar primero mataba _run_forever a mitad de
            # recv y dejaba el socket abierto: de ahí la excepción cosmética de
            # websockets al Ctrl-C. _consume tarda hasta ~5 s en mirar la señal
            # (timeout interno del recv); si no sale en 7 s, cancelar y silenciar.
            await self._stream.stop_ws()
            try:
                await asyncio.wait_for(runner, timeout=7)
            except (TimeoutError, asyncio.CancelledError):
                runner.cancel()
                try:
                    await runner
                except (asyncio.CancelledError, Exception):
                    pass
            await self._stream.close()  # no-op si el SDK ya cerró el socket
