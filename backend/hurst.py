"""Hurst rolling en vivo (Fase 2).

Consume barras de un `DataSource` polimórfico (LiveSource / ReplaySource) y
estima el exponente de Hurst (H) y la dimensión fractal (D = 2 - H) en ventana
móvil, vía DFA, como capa de contexto de régimen.

Separación de responsabilidades (de afuera hacia adentro):

    SessionFilter   -> qué barra cuenta (borde de entrada al buffer)
    HurstBuffer     -> mantiene la ventana de log-retornos + segmenta por
                       contigüidad temporal
    dfa()           -> SOLO calcula sobre una serie 1D limpia (importada de
                       docs/hurst_dfa.py, sin tocar)

`dfa()` se queda pura: todo el filtrado vive afuera. Esto preserva poder
validarla contra los sintéticos de hurst_dfa.py.

Convención Alpaca (no negociable): el timestamp de una barra marca el INICIO del
minuto. La barra de 09:30:00 cubre 09:30:00-09:31:00. Primera barra de sesión
regular: 09:30:00. Última: 15:59:00.
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# `dfa()` vive en docs/hurst_dfa.py (demo guardada bajo __main__, así que
# importarla NO ejecuta nada). La reutilizamos sin modificar ni reimplementar.
_DOCS = Path(__file__).resolve().parent.parent / "docs"
if str(_DOCS) not in sys.path:
    sys.path.insert(0, str(_DOCS))
from hurst_dfa import dfa  # noqa: E402

_ET = ZoneInfo("America/New_York")

# Sesión regular ET. Criterio: SESSION_OPEN <= hora_ET < SESSION_CLOSE.
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)

# Umbral de contigüidad temporal, derivado del timeframe y fijado por la física
# del dato, NO calibrable: barras contiguas distan 1 duración de barra; una
# barra faltante son 2 duraciones (se tolera); más que eso es un hueco real y
# corta el segmento. A 1m: tolerar 120 s, cortar >120 s. A 5m: tolerar 600 s,
# cortar >600 s. El cruce de día corta SIEMPRE, a cualquier timeframe.
GAP_CUT_BARS = 2

# --- Etiquetas de exclusión / estado (claves de las métricas) ---------------
EXCLUDED_OUT_OF_SESSION = "excluded_out_of_session"
EXCLUDED_FLAT = "excluded_flat"
NAN_INCOMPLETE = "nan_incomplete"      # buffer aún sin N retornos
NAN_SEGMENTATION = "nan_segmentation"  # buffer lleno pero sin segmento contiguo >= N
COMPUTED = "computed"                   # H calculado sobre datos limpios


class SessionFilter:
    """Borde de entrada al buffer: decide qué barra cuenta ANTES de que entre al
    buffer de log-retornos. Es stateless: sólo mira la barra."""

    def reason_to_exclude(self, bar) -> Optional[str]:
        """Devuelve la etiqueta de exclusión, o None si la barra es válida."""
        # Sesión regular en hora ET (zoneinfo, NUNCA offset UTC hardcodeado: debe
        # sobrevivir al cambio EDT/EST).
        t_et = bar.timestamp.astimezone(_ET).time()
        if not (SESSION_OPEN <= t_et < SESSION_CLOSE):
            return EXCLUDED_OUT_OF_SESSION
        # Velas planas (O==H==L==C): artefacto de baja cobertura IEX. Colapsan la
        # varianza residual del DFA y producen un H falso pero plausible. No
        # lanzan excepción; engañan en silencio. Se excluyen aun dentro de sesión.
        if bar.open == bar.high == bar.low == bar.close:
            return EXCLUDED_FLAT
        return None


@dataclass(slots=True)
class _Return:
    """Un log-retorno válido ya en el buffer, con su contexto de contigüidad."""

    ts: datetime          # timestamp (ET) de la barra que CIERRA el retorno
    logret: float
    is_break: bool        # True si este retorno cruza un hueco (gap > 2min o cambio de día)


class HurstBuffer:
    """Buffer rolling de los últimos N log-retornos válidos de UN símbolo, con
    segmentación por contigüidad temporal.

    - Recalcular H sólo al CIERRE de vela (lo hace el motor llamando a `compute`).
    - Segmentación antes de correr `dfa()`:
        * gap real entre timestamps consecutivos > 2 duraciones de barra
          (GAP_CUT_BARS)                                  -> corte de segmento.
        * cruce de día                                    -> corta SIEMPRE.
      Si la ventana no contiene un segmento contiguo de longitud >= N -> H = NaN.
    - Mientras el buffer no tenga N retornos válidos       -> H = NaN.
    """

    def __init__(self, window: int, bar_seconds: int = 60):
        if window < 1:
            raise ValueError("window debe ser >= 1")
        if bar_seconds < 1:
            raise ValueError("bar_seconds debe ser >= 1")
        self.window = window
        self._gap_cut = GAP_CUT_BARS * bar_seconds
        self._returns: list[_Return] = []
        self._prev: Optional[tuple[datetime, float]] = None  # (ts_et, close) válido anterior

    def add(self, ts_et: datetime, close: float) -> None:
        """Registra una barra ya filtrada (válida). Calcula el log-retorno contra
        la barra válida anterior y marca si cruza un hueco."""
        if self._prev is not None:
            prev_ts, prev_close = self._prev
            gap = (ts_et - prev_ts).total_seconds()
            same_day = ts_et.date() == prev_ts.date()
            is_break = (gap > self._gap_cut) or (not same_day)
            self._returns.append(
                _Return(ts=ts_et, logret=math.log(close / prev_close), is_break=is_break)
            )
            # Mantener la ventana a los últimos N retornos.
            if len(self._returns) > self.window:
                self._returns = self._returns[-self.window:]
        self._prev = (ts_et, close)

    def _longest_contiguous(self) -> list[float]:
        """El segmento contiguo más largo dentro de la ventana. Un retorno con
        is_break cruza un hueco: es inválido y CORTA el segmento (se descarta)."""
        best: list[float] = []
        cur: list[float] = []
        for r in self._returns:
            if r.is_break:
                cur = []
                continue
            cur.append(r.logret)
            if len(cur) > len(best):
                best = list(cur)
        return best

    def compute(self) -> tuple[float, str]:
        """Devuelve (H, estado). H puede ser NaN. NO corre DFA sobre datos rotos:
        preferir hueco visible a H inventado."""
        if len(self._returns) < self.window:
            return math.nan, NAN_INCOMPLETE
        segment = self._longest_contiguous()
        if len(segment) < self.window:
            return math.nan, NAN_SEGMENTATION
        # `dfa` recibe una serie limpia 1D y calcula. Puede devolver NaN por su
        # propio guard interno (N < 50); lo respetamos tal cual.
        return float(dfa(segment)), COMPUTED


@dataclass(slots=True)
class HurstResult:
    """Resultado por barra válida, listo para imprimir/loggear."""

    symbol: str
    timestamp: datetime  # tz-aware original (UTC tal como lo entrega Alpaca)
    H: float             # puede ser NaN
    D: float             # 2 - H (NaN si H es NaN)
    status: str          # COMPUTED | NAN_INCOMPLETE | NAN_SEGMENTATION


class HurstEngine:
    """Orquesta el pipeline para varios símbolos. Consume del `DataSource`
    polimórfico vía `on_bar(bar)` por cada vela cerrada — idéntico con Live o
    Replay. Lleva métricas de observabilidad por símbolo."""

    def __init__(
        self,
        symbols: Iterable[str],
        window: int = 120,
        windows: Optional[dict[str, int]] = None,
        bar_seconds: Optional[dict[str, int]] = None,
    ):
        """`windows` y `bar_seconds` son overrides por símbolo (ventana Hurst y
        duración de barra en segundos); un símbolo ausente usa `window` y 60 s.
        El umbral de corte de cada buffer se deriva de su duración de barra."""
        self.window = window
        self._windows = dict(windows or {})
        self._bar_seconds = dict(bar_seconds or {})
        self._filter = SessionFilter()
        self._buffers: dict[str, HurstBuffer] = {s: self._new_buffer(s) for s in symbols}
        self.stats: dict[str, Counter] = {s: Counter() for s in self._buffers}

    def _new_buffer(self, symbol: str) -> HurstBuffer:
        return HurstBuffer(
            self._windows.get(symbol, self.window),
            self._bar_seconds.get(symbol, 60),
        )

    def _buffer(self, symbol: str) -> HurstBuffer:
        buf = self._buffers.get(symbol)
        if buf is None:  # símbolo no anunciado al construir: alta perezosa
            buf = self._buffers[symbol] = self._new_buffer(symbol)
            self.stats[symbol] = Counter()
        return buf

    def on_bar(self, bar) -> Optional[HurstResult]:
        """Procesa una vela cerrada. Devuelve un HurstResult si la barra es válida
        (H puede ser NaN), o None si la barra se excluyó en el borde de entrada."""
        buf = self._buffer(bar.symbol)
        stats = self.stats[bar.symbol]

        reason = self._filter.reason_to_exclude(bar)
        if reason is not None:
            stats[reason] += 1
            return None

        ts_et = bar.timestamp.astimezone(_ET)
        buf.add(ts_et, bar.close)
        H, status = buf.compute()
        stats[status] += 1
        return HurstResult(
            symbol=bar.symbol,
            timestamp=bar.timestamp,
            H=H,
            D=2 - H,  # NaN-safe: 2 - NaN == NaN
            status=status,
        )

    def summary(self) -> dict[str, dict[str, int]]:
        """Métricas de exclusión/anulación por símbolo. NO mitiga sesgo; es dato
        de régimen (p.ej. muchas ventanas NaN ~14:00 ET = mercado paralizado
        pre-FOMC, se quiere ver, no enterrar)."""
        return {sym: dict(c) for sym, c in self.stats.items()}
