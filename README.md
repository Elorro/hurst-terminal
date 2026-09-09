# hurst-terminal

A personal market-regime terminal: rolling **Hurst exponent** (estimated by
Detrended Fluctuation Analysis) and fractal dimension **D = 2 − H** over Nasdaq
stocks, streamed from Alpaca.

It answers one question — *is this market trending, mean-reverting, or a random
walk right now?* — and nothing else. **It is a regime diagnostic, not a source of
trading signals.** H is read as it migrates across rolling windows; there is no
single "true" H for a series, and the global H over a full session is close to
useless.

## Status

Research instrument, single user. Phase 1 (data) and Phase 2 (live rolling
Hurst) are closed and verified; current work is accumulating evidence across
macro events under a labelling protocol fixed in advance. There is no UI, no
backtester, and no order routing — none are planned.

Two design commitments worth stating up front:

- **Verification is not calibration.** Parameters are fixed before a replay runs;
  the replay only verifies them. "It would look better with another window" is
  recorded as an observation, never applied.
- **A visible gap beats an invented number.** When a window is incomplete or the
  feed loses resolution, the output is NaN — missing data is itself regime
  information, so it is shown rather than filled.

## How it works

- A polymorphic `DataSource` emits `Bar` objects through one channel:
  `LiveSource` (WebSocket) and `ReplaySource` (historical REST + synthetic clock)
  are interchangeable, and the consumer cannot tell which one it is reading.
  Switching between them is a one-line config change.
- The pipeline runs outside-in: `SessionFilter` (which bars count — regular ET
  session, flat bars dropped) → `HurstBuffer` (rolling window of log-returns,
  segmented by contiguity) → a pure `dfa()` that only ever sees a clean 1-D
  series.
- Timeframes above 1m are derived locally by `BarResampler` from the same 1m
  stream, so a longer timeframe costs no extra subscription.

## Stack

Python 3 · NumPy · pandas · `alpaca-py` (IEX free feed) · asyncio. No framework,
no database — sessions persist to CSV. Pinned versions in `requirements.txt`.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example backend/.env      # add your Alpaca API keys

python backend/main.py            # Phase 1: bars to console
python backend/run_hurst.py       # Phase 2: rolling Hurst
python backend/validate_live.py   # live vs. replay cross-check
```

Replay works at any hour and is deterministic, so it is the default way to run
the project — set `SOURCE` in `backend/config.py`.

## Documentation

- `docs/spec-terminal-nasdaq.md` — full specification, architecture, scope.
- `docs/BITACORA.md` — engineering logbook (Spanish): decisions, reversals and
  verifications as they happened.
- `docs/hurst_dfa.py` — frozen reference DFA implementation, validated against
  synthetic series with known regimes.

## Disclaimer

Personal analysis and paper-trading tool. Nothing this project produces is
investment advice or a trading signal.

MIT licensed.
