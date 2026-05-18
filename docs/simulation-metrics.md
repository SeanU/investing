# Simulation metrics

This document defines the metrics that [`investing-simulate`](../src/investing/simulate_cli.py) computes for each simulation run and reports in aggregate. The reference implementation lives in [`src/investing/metrics.py`](../src/investing/metrics.py); the Quarto reports under [`reports/quarto/`](../reports/quarto/) reuse the same helpers so what you see on screen matches the parquet outputs.

Related docs:

- [`google-sheets-cli.md`](./google-sheets-cli.md): producing the price and dividend data the simulator consumes.
- [`instruments-cli.md`](./instruments-cli.md): maintaining the ticker metadata used by Sheets exports.

## How simulation runs become metrics

A single run is a list of `Portfolio` snapshots produced by [`investing.simulation.simulate`](../src/investing/simulation.py). Snapshots are taken on rebalance dates and at the simulation end date — irregular by design. The metrics layer re-samples them onto a **reporting cadence** (default: monthly) using [`investing.reporting.total_value_series`](../src/investing/reporting.py), which forward-fills the most recent holdings to each reporting date and prices them via `MarketHistory`. The forward-fill ensures values during long buy-and-hold stretches are still observed even though the simulator never created a snapshot there.

Every path metric (CAGR, max drawdown, std dev, Sortino) is computed from this resampled value series. Every aggregate metric (mean of CAGR across runs, terminal-wealth percentiles, success probability) operates on the per-run summaries.

## Reporting cadence

Configurable on `compute_simulation_metrics(..., reporting_frequency=...)` (default `"monthly"`). One of:

| Cadence | Sampling rule | Periods per year |
|---------|-----------------------------------------------------------------|------------------|
| `daily` | All trading days from `MarketHistory` between the run's start and end | 252 |
| `weekly` | Step by 7 calendar days, then union with trade dates | 52 |
| `monthly` | Step by calendar months (day-of-month clamped), then union with trade dates | 12 |

For `weekly`/`monthly`, trade dates are merged into the cadence so rebalance-day valuations are always observed. The `daily` cadence draws from the price-data calendar directly; it does not include weekends or holidays.

## Per-run metrics

The simulator produces one `RunMetrics` row per simulation run in `run_metrics.parquet`. Each is computed from the run's resampled value series `v[0], v[1], ..., v[n]`.

### CAGR

```
cagr = (v[n] / v[0]) ** (1 / horizon_years) - 1
```

where `horizon_years = (date[n] - date[0]).days / 365.25`. Returns `None` (NaN in parquet) if `v[0] <= 0`, `v[n] <= 0`, or `horizon_years <= 0`.

### Maximum drawdown

Worst peak-to-trough on the resampled series:

```
running_peak = max(v[0..k])
drawdown[k] = v[k] / running_peak - 1   # always <= 0
max_drawdown = min(drawdown[0..n])      # most negative
```

Reported as a negative fraction (e.g. `-0.42` for a 42% drawdown). Charts that display absolute drawdown should take `abs(...)` for readability.

### Annualized standard deviation

Population standard deviation of simple periodic returns, scaled by `sqrt(periods_per_year)`:

```
ret[k] = (v[k] - v[k-1]) / v[k-1]
sigma = pstdev(ret)
std_dev_returns = sigma * sqrt(periods_per_year)
```

Returns `None` if fewer than 2 periodic returns are available. Uses the population SD (`statistics.pstdev`) rather than sample SD; with hundreds of monthly observations the difference is negligible, but the choice is intentional and consistent with the Sortino downside-deviation computation below.

### Sortino ratio

Annualized excess return divided by annualized downside deviation against a minimum acceptable return (MAR):

```
mar_period = mar_annual / periods_per_year
downside[k] = min(0, ret[k] - mar_period)
downside_sigma = sqrt(mean(downside[k] ** 2))     # 0s for above-MAR returns count
downside_ann = downside_sigma * sqrt(periods_per_year)
mean_ann = mean(ret) * periods_per_year
sortino = (mean_ann - mar_annual) / downside_ann
```

Reported as `None` when the run had no downside deviations (all returns at or above the per-period MAR), since the ratio is undefined / infinite in that case. The MAR comes from the configured `target_annual_return` unless `sortino_target_return` is overridden in code.

### Terminal wealth

`v[n]` from the resampled series. Reported on each `RunMetrics` row as `terminal_wealth`.

## Aggregate metrics

The simulator also produces one `AggregateMetrics` row per strategy in `aggregate_metrics.parquet`. It summarizes the `RunMetrics` rows for that strategy.

| Field | Aggregation rule |
|----------------------------------|---------------------------------------------------------------------------|
| `cagr` | Mean of per-run `cagr`. |
| `max_drawdown` | Mean of per-run `max_drawdown`. |
| `std_dev_returns` | Mean of per-run `std_dev_returns`. |
| `sortino_ratio` | Mean of per-run `sortino_ratio` (runs with `None` are dropped). |
| `terminal_wealth_p10` | P10 of per-run `terminal_wealth` across the runs (linear interpolation). |
| `terminal_wealth_p50` | P50 of per-run `terminal_wealth`. |
| `terminal_wealth_p90` | P90 of per-run `terminal_wealth`. |
| `success_probability` | Fraction of runs whose `terminal_wealth >= success_target_wealth`. |
| `sortino_target_return_used` | Annual MAR actually used for Sortino across runs. |
| `success_target_wealth_used` | Terminal-wealth threshold used to compute `success_probability`. |

Path metrics are mean-averaged because each run is a sampled-with-shared-start-dates path, so the cross-run distribution can be inspected directly from `run_metrics.parquet` for richer questions (the per-strategy Quarto report does exactly this via `summarize_col`).

Terminal-wealth percentiles use linear interpolation between closest ranks, exposed as [`investing.metrics.percentile_linear`](../src/investing/metrics.py) and reused by the Quarto reports so the percentile definition is consistent end-to-end.

## Planning targets: MAR and success threshold

The simulation config requires `target_annual_return` (an annual decimal, e.g. `0.04` for 4%). The metrics engine derives two planning targets from it unless they are explicitly overridden in code:

- **Sortino MAR**: `sortino_target_return = target_annual_return`.
- **Success wealth threshold**: `success_target_wealth = starting_value * (1 + target_annual_return) ** horizon_years`, where `horizon_years` is taken from the first run's reporting dates.

Both resolved targets are written back into `AggregateMetrics` as `sortino_target_return_used` and `success_target_wealth_used` so the reports can name them explicitly.

If you want a separate MAR for risk-adjusted return versus a different threshold for "success", call `compute_simulation_metrics` directly with the overrides instead of via the CLI.

## Caveats

- **No fees, taxes, or cash flows.** The simulator reinvests all dividends into the paying ticker and does not apply expense ratios, capital-gains taxes, contributions, or withdrawals. Metrics reflect total-return gross of these effects.
- **Nominal, not real.** All values are nominal dollars; metrics are not deflated by inflation. For real-return analysis, deflate `terminal_wealth` and the `success_target_wealth` threshold by an exogenous CPI series before computing `success_probability`.
- **Shared start dates across strategies.** When multiple strategies are simulated in one config, `simulate_many` draws one start-date list and reuses it for every strategy. Per-`run_index` rows across strategies in `run_metrics.parquet` are therefore paired and can be compared directly (e.g. "did strategy A beat B on the same historical window?").
