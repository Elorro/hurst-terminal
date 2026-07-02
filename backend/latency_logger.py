"""Logger de latencia de barras en vivo — módulo reutilizable.

Por cada barra de 1m registra: símbolo, bar_ts (ET), recv_ts (ET, reloj local
sincronizado por NTP) y latencia_s = recv_ts - (bar_ts + 60 s).

Por qué el +60 s: Alpaca marca el timestamp al INICIO del minuto. La vela cubre
[bar_ts, bar_ts + 60 s) y no puede estar completa antes de bar_ts + 60 s. La
latencia mide, por tanto, el retardo desde que el minuto CIERRA hasta que la
barra llega a nuestro proceso — no incluye los 60 s de formación de la vela.

Al cierre de sesión o bajo demanda, `print_summary()` imprime min/mediana/p95/max
por símbolo. La mediana dice si el flujo es sano; el p95 delata problemas
intermitentes (stalls del WebSocket, pausas de GC, reconexiones).
"""

from __future__ import annotations

import math
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")


def ntp_synced() -> bool | None:
    """True/False según systemd; None si no se puede determinar."""
    try:
        out = subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True, text=True, timeout=3,
        )
        v = out.stdout.strip().lower()
        if v in ("yes", "true"):
            return True
        if v in ("no", "false"):
            return False
    except Exception:
        pass
    return None


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Percentil con interpolación lineal. `sorted_vals` debe venir ordenado."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


@dataclass(slots=True)
class LatencySample:
    symbol: str
    bar_ts: datetime    # ET, inicio del minuto
    recv_ts: datetime   # ET, recepción local
    latency_s: float


class LatencyLogger:
    def __init__(self, period_seconds: float = 60.0, echo: bool = False):
        self._period = timedelta(seconds=period_seconds)
        self._echo = echo
        self._by_symbol: dict[str, list[float]] = {}
        self.samples: list[LatencySample] = []
        self.ntp_ok = ntp_synced()

    def record(
        self, symbol: str, bar_ts: datetime, recv_ts: datetime | None = None
    ) -> LatencySample:
        if recv_ts is None:
            recv_ts = datetime.now(_ET)
        bar_ts_et = bar_ts.astimezone(_ET)
        recv_ts_et = recv_ts.astimezone(_ET)
        latency = (recv_ts_et - (bar_ts_et + self._period)).total_seconds()
        s = LatencySample(symbol, bar_ts_et, recv_ts_et, latency)
        self._by_symbol.setdefault(symbol, []).append(latency)
        self.samples.append(s)
        if self._echo:
            print(
                f"    [lat] {symbol:<5} bar={bar_ts_et:%H:%M:%S} "
                f"recv={recv_ts_et:%H:%M:%S.%f}"[:-3]
                + f"  lat={latency:+.2f}s",
                flush=True,
            )
        return s

    def summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for sym, vals in sorted(self._by_symbol.items()):
            sv = sorted(vals)
            out[sym] = {
                "n": float(len(sv)),
                "min": min(sv),
                "median": statistics.median(sv),
                "p95": _percentile(sv, 95),
                "max": max(sv),
            }
        return out

    def print_summary(self) -> None:
        print("\n=== Latencia de barras de 1m (s) — recv_ts - (bar_ts + 60s) ===")
        ntp_str = {True: "sí", False: "NO", None: "?"}[self.ntp_ok]
        print(f"reloj NTP-sincronizado: {ntp_str}")
        if not self.samples:
            print("(sin muestras)")
            return
        print(f"{'símbolo':<7} {'n':>4} {'min':>8} {'mediana':>8} {'p95':>8} {'max':>8}")
        for sym, st in self.summary().items():
            print(
                f"{sym:<7} {int(st['n']):>4} {st['min']:>8.2f} "
                f"{st['median']:>8.2f} {st['p95']:>8.2f} {st['max']:>8.2f}"
            )
