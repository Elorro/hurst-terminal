"""Agregadores OHLC.

Dos piezas independientes:

- `OHLCAggregator`: trades -> velas de 1m. Esqueleto del modo B (brief §3,
  spec §4.2). NO está en el camino crítico; se activa con LIVE_MODE = "B".

- `BarResampler`: velas de 1m -> velas de un múltiplo (p.ej. 5m), por agregación
  local. Esto permite derivar timeframes superiores sin una suscripción aparte,
  y es lo que se cruza contra la 5m de Alpaca para validar el agregador.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sources.base import Bar


def _floor_to_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


class OHLCAggregator:
    """Agrupa trades en velas de 1m por símbolo. Emite la vela al cambiar de
    minuto (cuando llega el primer trade del minuto siguiente)."""

    def __init__(self):
        # symbol -> vela en construcción {minute, o, h, l, c, v}
        self._building: dict[str, dict] = {}

    def add_trade(self, trade) -> Optional[Bar]:
        symbol = trade.symbol
        price = float(trade.price)
        size = float(getattr(trade, "size", 0) or 0)
        minute = _floor_to_minute(
            getattr(trade, "timestamp", datetime.now(timezone.utc))
        )

        cur = self._building.get(symbol)
        if cur is None:
            self._building[symbol] = self._new_bar(minute, price, size)
            return None

        if minute > cur["minute"]:
            closed = self._emit(symbol, cur)
            self._building[symbol] = self._new_bar(minute, price, size)
            return closed

        # mismo minuto: actualizar OHLCV
        cur["high"] = max(cur["high"], price)
        cur["low"] = min(cur["low"], price)
        cur["close"] = price
        cur["volume"] += size
        return None

    @staticmethod
    def _new_bar(minute, price, size) -> dict:
        return {
            "minute": minute,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": size,
        }

    @staticmethod
    def _emit(symbol: str, cur: dict) -> Bar:
        return Bar(
            symbol=symbol,
            timestamp=cur["minute"],
            open=cur["open"],
            high=cur["high"],
            low=cur["low"],
            close=cur["close"],
            volume=cur["volume"],
        )


class BarResampler:
    """Agrega velas de 1m en velas de `minutes` por ventanas de reloj alineadas
    (..09:30, 09:35, 09:40..). Emite la vela cuando llega una barra de una
    ventana posterior; `flush()` cierra las ventanas en construcción.

    `last_count` guarda cuántas velas de 1m formaron la última vela emitida, útil
    para distinguir ventanas completas (5 barras) de incompletas al cruzar contra
    Alpaca.
    """

    def __init__(self, minutes: int = 5):
        if 60 % minutes != 0:
            raise ValueError("minutes debe dividir 60 para alinear al reloj")
        self._minutes = minutes
        self._building: dict[str, dict] = {}
        self.last_count: dict[tuple[str, datetime], int] = {}

    def _window(self, ts: datetime) -> datetime:
        m = (ts.minute // self._minutes) * self._minutes
        return ts.replace(minute=m, second=0, microsecond=0)

    def add_bar(self, bar: Bar) -> Optional[Bar]:
        window = self._window(bar.timestamp)
        cur = self._building.get(bar.symbol)
        if cur is None:
            self._building[bar.symbol] = self._start(window, bar)
            return None
        if window > cur["window"]:
            closed = self._emit(bar.symbol, cur)
            self._building[bar.symbol] = self._start(window, bar)
            return closed
        # misma ventana: actualizar OHLCV
        cur["high"] = max(cur["high"], bar.high)
        cur["low"] = min(cur["low"], bar.low)
        cur["close"] = bar.close
        cur["volume"] += bar.volume
        cur["count"] += 1
        return None

    def flush(self) -> list[Bar]:
        out = [self._emit(sym, cur) for sym, cur in self._building.items()]
        self._building.clear()
        return out

    @staticmethod
    def _start(window: datetime, bar: Bar) -> dict:
        return {
            "window": window,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "count": 1,
        }

    def _emit(self, symbol: str, cur: dict) -> Bar:
        self.last_count[(symbol, cur["window"])] = cur["count"]
        return Bar(
            symbol=symbol,
            timestamp=cur["window"],
            open=cur["open"],
            high=cur["high"],
            low=cur["low"],
            close=cur["close"],
            volume=cur["volume"],
        )
