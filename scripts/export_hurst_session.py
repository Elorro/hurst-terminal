"""Export portfolio artifacts (PNG + SVG + JSON) from an ALREADY COMPUTED
Hurst/D session CSV. Read-only over `outputs/`: this script never recomputes
H, never touches the engine, and never contacts a data source.

Usage:
    python scripts/export_hurst_session.py <hurst_csv> <out_dir> [--label TEXT]
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

# Bar timestamps are tz-aware ET; matplotlib formats dates in rcParams["timezone"]
# (UTC) unless told otherwise, which would silently shift every label by the
# offset of the day. Always format on the exchange clock.
ET = ZoneInfo("America/New_York")

PALETTE = {
    "bg": "#0a0e16", "panel": "#0f1622", "edge": "#2a3a55",
    "text": "#e8ecf3", "muted": "#7d8aa3", "grid": "#1b2436",
    "teal": "#4fd6c8", "amber": "#ffb347", "red": "#ff7b72",
}


def read_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        h, d = r["H"].strip(), r["D"].strip()
        out.append({
            "symbol": r["symbol"],
            "bar_ts": r["bar_ts"],
            "H": float(h) if h else None,
            "D": float(d) if d else None,
            "status": r["status"],
        })
    return out


def plot(rows: list[dict], out_dir: Path, stem: str, label: str) -> tuple[Path, Path, dict]:
    ts = [datetime.fromisoformat(r["bar_ts"]).astimezone(ET) for r in rows]
    # NaN (not zero) keeps the gaps visible: a missing H is regime information.
    h = np.array([r["H"] if r["H"] is not None else np.nan for r in rows], dtype=float)

    finite = np.flatnonzero(np.isfinite(h))
    i_min = int(finite[np.argmin(h[finite])])
    session_day = ts[0].date()
    announcement = ts[0].replace(hour=14, minute=0, second=0, microsecond=0)

    plt.rcParams.update({
        "figure.facecolor": PALETTE["bg"], "axes.facecolor": PALETTE["panel"],
        "axes.edgecolor": PALETTE["edge"], "text.color": PALETTE["text"],
        "axes.labelcolor": "#b8c2d6", "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"], "font.family": "monospace",
        "axes.grid": True, "grid.color": PALETTE["grid"], "grid.linewidth": 0.6,
    })

    fig, ax = plt.subplots(figsize=(12, 5.2))
    ax.plot(ts, h, color=PALETTE["teal"], lw=1.5, solid_capstyle="round")
    ax.fill_between(ts, 0.5, h, where=(h >= 0.5), color=PALETTE["teal"], alpha=0.16)
    ax.fill_between(ts, 0.5, h, where=(h < 0.5), color=PALETTE["red"], alpha=0.16)

    ax.axhline(0.5, color=PALETTE["muted"], ls="--", lw=1.0)
    ax.text(ts[0], 0.505, "H = 0.5  random walk", color=PALETTE["muted"],
            fontsize=8, va="bottom")

    ax.axvline(announcement, color=PALETTE["amber"], ls="--", lw=1.0, alpha=0.85)
    ax.annotate("FOMC statement 14:00 ET", xy=(announcement, 0.82), xytext=(-8, 0),
                textcoords="offset points", color=PALETTE["amber"],
                fontsize=8.5, va="center", ha="right")

    ax.plot([ts[i_min]], [h[i_min]], "o", ms=7, color=PALETTE["red"],
            mec=PALETTE["bg"], mew=1.2, zorder=5)
    ax.annotate(f"session low  H={h[i_min]:.3f}  {ts[i_min]:%H:%M} ET",
                xy=(ts[i_min], h[i_min]), xytext=(10, -22),
                textcoords="offset points", color=PALETTE["red"], fontsize=8,
                arrowprops=dict(arrowstyle="-", color=PALETTE["red"], lw=0.8))

    ax.text(0.995, 0.04,
            "gaps = windows without a defined H (not zeros)",
            transform=ax.transAxes, ha="right", color=PALETTE["muted"], fontsize=7.5)

    ax.set_ylabel("H (Hurst exponent, DFA)")
    ax.set_xlabel(f"time of day (ET) — {session_day:%Y-%m-%d} regular session")
    ax.set_xlim(ts[0], ts[-1])
    ax.set_ylim(0.15, 0.85)
    ax.xaxis.set_major_locator(mdates.HourLocator(tz=ET))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=ET))
    ax.set_title(label, loc="left", fontsize=13, color=PALETTE["text"])

    fig.tight_layout()
    png = out_dir / f"{stem}.png"
    svg = out_dir / f"{stem}.svg"
    fig.savefig(png, dpi=150, facecolor=PALETTE["bg"])
    fig.savefig(svg, facecolor=PALETTE["bg"])
    plt.close(fig)

    meta = {
        "min_H": float(h[i_min]),
        "min_ts": rows[i_min]["bar_ts"],
        "computed": int(np.isfinite(h).sum()),
        "rows": len(rows),
    }
    return png, svg, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--label", default="Rolling Hurst exponent")
    ap.add_argument("--stem", default=None)
    args = ap.parse_args()

    rows = read_rows(args.csv_path)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.stem or args.csv_path.stem
    png, svg, meta = plot(rows, args.out_dir, stem, args.label)

    payload = {
        "source_csv": args.csv_path.name,
        "symbol": rows[0]["symbol"],
        "session_date": rows[0]["bar_ts"][:10],
        "timeframe": "1m",
        "window": 120,
        "note": "H/D as computed by the engine; null means no defined H "
                "(incomplete window or segment break), never 0.",
        "series": rows,
    }
    js = args.out_dir / f"{stem}.json"
    js.write_text(json.dumps(payload, indent=2) + "\n")

    print(f"rows={meta['rows']} computed={meta['computed']} "
          f"null={meta['rows'] - meta['computed']} "
          f"min_H={meta['min_H']:.3f} @ {meta['min_ts']}")
    for p in (png, svg, js):
        print(f"  wrote {p}")


if __name__ == "__main__":
    main()
