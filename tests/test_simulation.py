from datetime import date, timedelta

from investing.history import load_market_history
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import AnnualRebalance, monthly_time_step, simulate


def test__smoke_test():
    history = load_market_history("data/5-way-prices.xlsx", "data/5-way-dividends.xlsx")
    strategy = AnnualRebalance(
        AssetAllocation(
            [HoldingTarget(ticker, 1) for ticker in history.securities.keys()]
        ),
        0.05,
    )
    simulate(history, date(2022, 1, 1), 100_000, strategy, monthly_time_step)
