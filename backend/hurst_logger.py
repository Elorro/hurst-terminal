"""Volcado incremental del stream de H/D a CSV — módulo reutilizable.

Mismo patrón que `latency_logger.py`: el archivo se abre al construir, cada fila
se escribe **en el momento** (`buffering=1`: flush en cada `\\n`) y la escritura
es best-effort — si el disco falla, se avisa y la captura sigue. Persistir la
medición nunca puede tumbar la corrida que se está midiendo.

Qué se registra: **una fila por cada barra que el motor PROCESA** (todo
`HurstResult`), incluidos los estados NaN. La ausencia de H alrededor de un
evento macro no es ruido a descartar, es dato de régimen (§8: mercado paralizado
o feed sin resolución); enterrarla en el CSV sería justo lo contrario de lo que
la BITACORA viene sosteniendo. En las filas NaN, H y D van **vacíos** (no la
cadena "nan"): pandas los lee como NaN sin conversión y el `status` ya dice el
motivo.

Qué NO se registra: las barras excluidas en el borde de entrada (fuera de
sesión, velas planas). El motor no devuelve resultado para ellas y re-derivar
aquí el motivo duplicaría `SessionFilter` fuera del motor — un segundo juez que
puede divergir del real. Su conteo vive en el resumen de observabilidad por
sesión. Consecuencia aceptada: un minuto sin fila es una barra que no entró al
buffer, pero el CSV no distingue "plana" de "ausente del feed" (§10).
"""

from __future__ import annotations

import math
from pathlib import Path
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

CSV_HEADER = "symbol,bar_ts,H,D,status"


def _fmt(x: float) -> str:
    """Vacío si NaN. Más decimales que la consola (3): el CSV es para comparar
    sesiones entre sí, no para leerlo a ojo."""
    return "" if math.isnan(x) else f"{x:.6f}"


class HurstLogger:
    """Escribe cada `HurstResult` a un CSV por corrida. No toca el motor: solo
    consume lo que `HurstEngine.on_bar()` ya produce."""

    def __init__(self, csv_path: str | Path | None = None):
        self.csv_path: Path | None = Path(csv_path) if csv_path else None
        self.rows = 0
        self._fh = None
        if self.csv_path is not None:
            self._open_sink()

    def _open_sink(self) -> None:
        """Se abre al construir, no en la primera fila: así el archivo existe
        desde el arranque y se puede seguir con `tail -f` durante la sesión."""
        try:
            self.csv_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
            self._fh = open(self.csv_path, "a", buffering=1, newline="")
            if new:
                self._fh.write(CSV_HEADER + "\n")
        except OSError as e:
            print(f"[hurst-csv] aviso: no se pudo abrir {self.csv_path} ({e}); "
                  "los resultados solo van a consola", flush=True)
            self._fh = None

    def record(self, res) -> None:
        """Una fila por resultado. El timestamp va en ET: es el eje sobre el que
        se comparan sesiones (y el que usa la consola)."""
        if self._fh is None:
            return
        try:
            ts_et = res.timestamp.astimezone(_ET)
            self._fh.write(
                f"{res.symbol},{ts_et.isoformat()},{_fmt(res.H)},{_fmt(res.D)},"
                f"{res.status}\n"
            )
            self.rows += 1
        except OSError as e:
            print(f"[hurst-csv] aviso: fallo al escribir fila ({e}); "
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
