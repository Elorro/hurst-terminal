# hurst-terminal

A personal market-regime research tool: a rolling Hurst exponent (via DFA) and
fractal dimension computed live over Nasdaq equities (currently NVDA). **Regime
diagnostics, not trading signals** — a deliberate design boundary, explained
below.

> Research instrument, single-user. Not a deployed service, not investment advice.

---

## What it does

For a price series, it estimates the **Hurst exponent (H)** over a rolling window
using **Detrended Fluctuation Analysis (DFA)**, and derives the **fractal
dimension** D = 2 − H. The reading classifies the *regime* of the series:

- **H > 0.5** — persistent / trending (D < 1.5, smoother path)
- **H ≈ 0.5** — random walk, no exploitable memory (D ≈ 1.5)
- **H < 0.5** — anti-persistent / mean-reverting (D > 1.5, rougher path)

DFA is used over classical R/S because it is far more robust on the short, noisy
windows that intraday data produces. The estimator is validated against synthetic
series with three distinct regimes, correctly recovering their **ordering and
separation** (trending > random > mean-reverting) — not their absolute
magnitudes, since the synthetic generator uses a nominal H, not a true fBm H.

## The core design decision (and why it matters)

The indicator is a **regime-context layer, not a timing signal.** H is never
thresholded to emit buy/sell triggers. This is a rigor decision, not a missing
feature: optimizing H thresholds to generate signals is a direct path to
overfitting on a single-parameter indicator. H is used to *describe* the regime
(is the market trending or mean-reverting right now?), which is genuinely useful
context, while refusing to overclaim predictive power it doesn't have.

## Engineering

- **Polymorphic data source**: one `DataSource` interface, two interchangeable
  implementations — `LiveSource` (Alpaca WebSocket) and `ReplaySource` (historical
  REST + clock) — emitting the same `Bar` type. Switching live↔replay is a config
  change; the consumer is identical. This let every result be verified in
  deterministic replay before being trusted live.
- **Regime pipeline**: `SessionFilter` (which bars count) → `HurstBuffer` (rolling
  window + contiguity segmentation) → pure `dfa()` (computes on a clean 1-D series).
  Filtering lives at the buffer's edge; `dfa()` stays pure and independently
  verifiable.
- **Honest handling of data gaps**: bars are segmented by temporal contiguity;
  a real gap breaks the segment and yields NaN rather than a fabricated H —
  "prefer a visible hole to an invented value." NaN is recorded as regime data.
- Survived a real mid-capture network drop (upstream DNS) without corrupting the
  series; the announcement window verified bit-for-bit identical (36/36 bars)
  between live and replay.

## Method (the part I'm most deliberate about)

- **Parameters are fixed by reasoning *before* verification runs; results never
  choose parameters retroactively.** Verification ≠ calibration.
- **A falsified hypothesis, documented**: extending the tool to a second ticker
  (AMD) at multiple timeframes was tested against fixed dates and *failed* — the
  free IEX feed lacks the coverage resolution for it. The hypothesis was recorded
  as falsified and the ticker scoped out, rather than the parameters bent to
  rescue it.
- **Pre-registered observation protocol**: before accumulating event sessions, a
  falsifiable primary hypothesis and fixed measurement windows are defined in
  advance, and *every* captured session enters the record regardless of outcome
  (guard against survivorship bias).

## Current state (honest inventory)

Replay and live are kept strictly distinct throughout — a replayed historical
session and a live capture are different evidence, and the project never counts
them as the same thing. All figures below are from `docs/BITACORA.md`.

- **Estimator validated**: DFA against synthetic series with three distinct
  regimes — ordering and separation, not absolute magnitudes.
- **Verified by replay — 1 historical session**: FOMC, 17 June 2026, NVDA at
  1-min bars / 120-bar window: 390 contiguous bars, 270 H values, zero segment
  breaks.
- **Captured live — 2 real macro-event sessions**, each cross-checked by
  replaying the same day:
  - **NFP, 2 July 2026** — the replay reproduced the capture exactly (missing
    bars, segment break, states and H all identical): **zero divergence**. The
    8:30 AM ET release is pre-market, so the announcement itself falls outside
    the pipeline's session window.
  - **FOMC, 29 July 2026** — 254 of 265 H values identical to three decimals;
    the remaining 11 differ by +0.001, from late revisions in the historical
    record rather than engine divergence. The announcement window (1:45–2:20 PM
    ET) matched **36/36 bars exactly**, with H = 0.433 at 2:00 PM in both. An
    upstream-DNS drop early in the session cost 3 irrecoverable minutes of market
    data, delaying the first reading from 11:30 to 11:35 and yielding 265 H
    instead of 270 — a bounded delay, not a contaminated session.
- **Regime signature so far**: across the two FOMC sessions (June replay, July
  live), **two of three phases coincide** — an anti-persistent pre-announcement
  stretch, and the session's minimum H landing at the 2:00 PM ET release. The
  third **diverged outright**: 80 of 106 minutes above H > 0.6 after the July
  release, against 5 of 106 in June. **n = 2 is an anecdote, not a pattern**;
  systematic validation is in progress under the pre-registered protocol.
- **Stack**: Python 3.14, `alpaca-py`, `numpy`, `pandas`. Data: Alpaca free-tier
  IEX feed.

## Selected visuals

- `portfolio-assets/fomc-2026-06-17-nvda-hurst.(png|svg)` — rolling H over the
  June 2026 FOMC session, with the 2:00 PM ET release annotated and the day's
  minimum marked. One illustrative session; not a validated pattern.
- `portfolio-assets/synthetic-three-regimes.png` — DFA estimator ordering and
  separating three synthetic regimes.

## Repo map

- `backend/` — data sources, session filter, Hurst engine, loggers
- `docs/hurst_dfa.py` — the DFA estimator + synthetic validation demo
- `docs/BITACORA.md` — engineering logbook (Spanish): every decision, reversal,
  and verification, with the reasoning behind it
- `docs/spec-terminal-nasdaq.md` — full technical specification
- `scripts/` — reproducible export scripts for the portfolio assets
