"""Interfaz común de fuente de datos.

El resto del pipeline (consumidor en Fase 1, Hurst más adelante) consume `Bar`
a través de `DataSource.stream()` y no sabe ni le importa de qué implementación
concreta viene cada barra. Esa simetría es lo que permite cambiar de fuente con
solo tocar la config.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator


@dataclass(slots=True)
class Bar:
    """Vela OHLC normalizada, independiente del origen (live o replay)."""

    symbol: str
    timestamp: datetime  # tz-aware (UTC tal como lo entrega Alpaca)
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_alpaca(cls, bar) -> "Bar":
        """Convierte un `alpaca.data.models.Bar` a nuestro `Bar`."""
        return cls(
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )


class DataSource(ABC):
    """Fuente de barras. Cada implementación emite `Bar` por el mismo canal."""

    @abstractmethod
    def stream(self) -> AsyncIterator[Bar]:
        """Async generator que produce barras hasta agotarse (replay) o
        indefinidamente (live). El consumidor solo hace `async for bar in ...`."""
        raise NotImplementedError
