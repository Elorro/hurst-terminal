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

Persistencia (bitácora §11): el resumen NO responde la pregunta de §7 — si la
cola de latencia se concentra en el evento o está repartida. Por eso, con
`csv_path`, cada muestra se escribe a disco **en el momento** (línea a línea,
flush inmediato): un corte de red o un kill pierde lo que no ocurrió, no lo ya
capturado. La escritura es best-effort: si falla, se avisa y la captura sigue —
persistir la medición nunca puede tumbar la corrida que se está midiendo.
"""

from __future__ import annotations

import math
import statistics
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CSV_HEADER = "symbol,bar_ts,recv_ts,latency_s"

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
    def __init__(
        self,
        period_seconds: float = 60.0,
        echo: bool = False,
        csv_path: str | Path | None = None,
    ):
        self._period = timedelta(seconds=period_seconds)
        self._echo = echo
        self._by_symbol: dict[str, list[float]] = {}
        self.samples: list[LatencySample] = []
        self.ntp_ok = ntp_synced()
        self.csv_path: Path | None = Path(csv_path) if csv_path else None
        self._fh = None
        if self.csv_path is not None:
            self._open_sink()

    def _open_sink(self) -> None:
        """Abre el CSV en modo línea-a-línea (buffering=1: cada `\\n` va al SO).

        Se abre al construir, no en la primera muestra: así el archivo existe
        desde el arranque y se puede seguir con `tail -f` durante la sesión.
        """
        try:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
            self._fh = open(self.csv_path, "a", buffering=1, newline="")
            if new:
                self._fh.write(CSV_HEADER + "\n")
        except OSError as e:
            print(f"[lat] aviso: no se pudo abrir {self.csv_path} ({e}); "
                  "las muestras solo quedan en memoria", flush=True)
            self._fh = None

    def _write_sample(self, s: LatencySample) -> None:
        if self._fh is None:
            return
        try:
            self._fh.write(
                f"{s.symbol},{s.bar_ts.isoformat()},{s.recv_ts.isoformat()},"
                f"{s.latency_s:.3f}\n"
            )
        except OSError as e:
            print(f"[lat] aviso: fallo al escribir muestra ({e}); "
                  "se desactiva el volcado a disco", flush=True)
            self.close()

    def close(self) -> None:
        """Idempotente: cerrar dos veces no es error."""
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None

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
        self._write_sample(s)
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
