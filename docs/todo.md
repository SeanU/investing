# TODO

Deferred improvements for the `investing` package. These have been triaged out of the current implementation pass but are valuable to revisit. Each item lists why it matters, the rough scope, and any preconditions.

This file is curated by hand. When picking up an item, promote it into a plan under `.cursor/plans/` and link back here.

---

## 1. Cash flows: contributions and withdrawals

**Why.** The current engine in [`src/investing/simulation.py`](../src/investing/simulation.py) holds the starting capital constant. There is no way to model:

- Monthly DCA into a strategy during accumulation.
- Retirement drawdown policies (constant-dollar 4% SWR, fixed-percentage, VPW, Guyton–Klinger guardrails).
- Lump-sum events.

Without cash flows, terminal-wealth metrics and the success-probability threshold both miss the most relevant retirement-planning questions.

**Scope.**

- Extend `SimulationConfig` in [`src/investing/simulate_cli.py`](../src/investing/simulate_cli.py) with a `cash_flows` block: either a fixed schedule (e.g. `{ "monthly_contribution": 1500 }`) or a named withdrawal policy with parameters.
- Add a cash-flow application step in `simulate(...)` in [`src/investing/simulation.py`](../src/investing/simulation.py), invoked alongside dividend reinvestment. Withdrawals draw from holdings using a deterministic priority (most-overweight ticker, or pro-rata).
- Introduce a `CASH` position class (or a `cash` field on `Portfolio`) so withdrawals/contributions don't have to instantaneously settle into securities — important for realistic SWR modeling.
- New Parquet schema in the simulation output: `cash_flows.parquet` with `(strategy, run_index, event_date, kind, amount)`.
- Update metrics: `success_probability` should also report "probability of running out before horizon" (any month with portfolio value ≤ 0) once withdrawals exist.

**Preconditions.** None. Loosely coupled to "More strategies" (the withdrawal policies are themselves new strategies in a sense, or new policy objects orthogonal to allocation/rebalancing).

---

## 2. Bootstrap / block-bootstrap return sampling

**Why.** Today, `_random_start_dates` in [`src/investing/simulation.py`](../src/investing/simulation.py) samples a uniform calendar start date and replays a single contiguous historical window per run. With ~30 years of price history and a 30-year horizon, the start-date window collapses to one or two years and all runs share nearly the same path. This is *historical resampling*, not Monte Carlo, and the variance across runs is misleadingly small.

**Scope.**

- New sampler module (e.g. `src/investing/sampling.py`) with implementations:
  - Existing contiguous-window sampler (refactored out of `simulation.py`).
  - IID bootstrap of monthly returns.
  - Politis–Romano stationary block bootstrap of monthly returns.
- A `SyntheticMarketHistory` wrapper that exposes the same `get_price(...)` / `get_dividends_by_payment_date(...)` interface as `MarketHistory`, but constructs a price path from sampled return blocks. Dividend handling: either resample dividend yields on the same block boundaries or scale by trailing yield.
- Selectable via config: `"sampler": { "type": "contiguous" | "iid_bootstrap" | "block_bootstrap", "block_mean_length_months": 12 }`.
- Keep the contiguous default so existing reports reproduce.

**Preconditions.** None, but compounds nicely with cash flows (item 1) since true Monte Carlo paths exercise sequence-of-returns risk more thoroughly than overlapping historical windows.

---

## 3. More allocation / rebalancing strategies

**Why.** The current strategy menu in [`src/investing/simulation.py`](../src/investing/simulation.py) has only `BuyAndHold` and `AnnualRebalance` (threshold-gated, fires at most once per year). Several common real-world policies aren't expressible.

**Scope.** Each is a new subclass of `Strategy`, plus a config schema branch in [`src/investing/simulate_cli.py`](../src/investing/simulate_cli.py) under `rebalancing.type`:

- **Periodic calendar rebalance** at monthly, quarterly, or annual cadence. Generalize `AnnualRebalance.next_rebalance` to step by the configured frequency.
- **Pure threshold-band rebalance.** Rebalance whenever any holding drifts past the band, irrespective of calendar. `next_rebalance` returns "as soon as any drift check is triggered" — handled by the engine making a drift check at every reporting date.
- **Manual glide path.** Strategy config = list of `(date, allocation)` waypoints, linearly interpolated by date. Verifies against pre-packaged target-date funds like VTHRX.
- **Risk parity / inverse-vol weights.** At each rebalance, look up a trailing window of returns from `MarketHistory` and set weights inversely proportional to per-asset volatility (clamped, no leverage).

**Cleanup also worth doing in the same pass:** `AnnualRebalance` stores `starting_allocation` via `Strategy.__init__` *and* a redundant `self.allocation`. The recursive `_distribute_overallocations` / `_distribute_underallocations` methods recompute proportions each call — replaceable with a single deterministic "solve for the trade vector that hits the target proportions" step. Faster and easier to test.

**Preconditions.** Risk parity needs a stable way to query trailing returns through `MarketHistory`; the existing `_price_index` is enough but the helper should probably live alongside `trading_days(...)` once that lands (see A1.3).

---

## 4. Paired same-start-date comparisons

**Why.** `simulate_many` in [`src/investing/simulation.py`](../src/investing/simulation.py) (lines 570–573) intentionally shares the sampled start-date list across all strategies, so per-`run_index` results across strategies are paired. The current [`reports/quarto/comparison_report.qmd`](../reports/quarto/comparison_report.qmd) throws that pairing away and only reports side-by-side marginal statistics. Paired statistics are far more decision-relevant: "Strategy A beat B in 78% of paired runs (p < 0.001)" beats "A's mean CAGR is 6.4% and B's is 6.2%".

**Scope.**

- New helper module (`src/investing/comparison.py`) or additions to [`src/investing/metrics.py`](../src/investing/metrics.py):
  - `pairwise_deltas(run_metrics_df, metric)`: for each pair of strategies, returns the per-`run_index` Δ values.
  - `win_rate(run_metrics_df, metric)`: fraction of runs where A > B per pair.
  - `wilcoxon_p(run_metrics_df, metric)`: Wilcoxon signed-rank p-value per pair.
- In [`reports/quarto/comparison_report.qmd`](../reports/quarto/comparison_report.qmd):
  - Δ-wealth histogram per pair.
  - Win-rate matrix (strategy × strategy heatmap of win rates on terminal wealth or CAGR).
  - "Strategy vs. strategy" wealth-ratio line chart (median across paired runs of A/B at each date) — depends on the aligned wealth-paths helper from the A2 plan.
- New tests in [`tests/test_metrics.py`](../tests/test_metrics.py) (or `test_comparison.py`) covering each helper against hand-computed fixtures.

**Preconditions.** Wealth-ratio chart benefits from the `wealth_paths(...)` helper specified in the A2 plan (`fan_charts_drift`). Win-rate matrix and Wilcoxon work directly off `run_metrics.parquet` with no new infrastructure.

---

## Rejected (for the record, do not implement)

These were explicitly rejected during triage and are recorded here so they don't get re-proposed without intent:

- Real-return reporting (CPI deflation).
- Fund expense ratios and taxable-account tax drag.
- Extra risk metrics (Calmar, Ulcer / time-underwater, CVaR of terminal wealth, failure curve).
