from datetime import date

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p


def _market_history_for_a_and_b() -> h.MarketHistory:
    return h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 1, 2), 11.0),
                    d.Price(date(2026, 1, 3), 12.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 1, 1), 20.0),
                    d.Price(date(2026, 1, 2), 21.0),
                    d.Price(date(2026, 1, 3), 22.0),
                ],
                [],
            ),
        }
    )


def test_sell_reduces_oldest_lots_first_when_amount_spans_multiple_lots():
    """Given: two A lots; sell amount spans both lots.

    Example input:
      - Lots: A(2026-01-01, qty=10), A(2026-01-02, qty=8)
      - Trade date: 2026-01-03
      - A price on trade date: 12.0
      - Sell amount: 144.0 (12 shares)

    Expected output:
      - Remaining A lots: one lot from 2026-01-02 with qty=6
      - Sell trades recorded: 2 (qty 10, then qty 2)
      - Remaining A value: 72.0
    """
    history = _market_history_for_a_and_b()
    portfolio = p.Portfolio(
        date(2026, 1, 3),
        [
            p.Holding("A", date(2026, 1, 1), 10.0, 10.0, date(2026, 1, 3), 12.0),
            p.Holding("A", date(2026, 1, 2), 11.0, 8.0, date(2026, 1, 3), 12.0),
        ],
    )

    new_portfolio = portfolio.sell(
        ticker="A",
        amount=144.0,
        trade_date=date(2026, 1, 3),
        prices=history,
    )

    holdings_by_ticker = new_portfolio.holdings_by_ticker()
    assert set(holdings_by_ticker.keys()) == {"A"}
    assert len(holdings_by_ticker["A"]) == 1
    remaining_lot = holdings_by_ticker["A"][0]
    assert remaining_lot.purchase_date == date(2026, 1, 2)
    assert remaining_lot.quantity == pytest.approx(6.0)

    sell_trades = [t for t in new_portfolio.trades if t.kind == "sell" and t.ticker == "A"]
    assert len(sell_trades) == 2
    assert sell_trades[0].quantity == pytest.approx(10.0)
    assert sell_trades[1].quantity == pytest.approx(2.0)

    values = new_portfolio.value_by_ticker()
    assert values["A"] == pytest.approx(72.0)


def test_sell_exact_lot_amount_removes_lot_without_remainder():
    """Given: one A lot; sell exactly that lot's current value.

    Example input:
      - Lot: A(2026-01-01, qty=10), A(2026-01-02, qty=8)
      - Trade date: 2026-01-03
      - A price on trade date: 12.0
      - Sell amount: 120.0 (10 shares)

    Expected output:
      - Exactly one lot of A remains: the 8 shares purchased 2026-01-02.
      - Sell trades recorded: 1
      - Sold quantity: 10
    """
    history = _market_history_for_a_and_b()
    portfolio = p.Portfolio(
        date(2026, 1, 3),
        [
            p.Holding("A", date(2026, 1, 1), 10.0, 10.0, date(2026, 1, 3), 12.0),
            p.Holding("A", date(2026, 1, 2), 11.0, 8.0, date(2026, 1, 3), 12.0),
        ],
    )

    new_portfolio = portfolio.sell(
        ticker="A",
        amount=120.0,
        trade_date=date(2026, 1, 3),
        prices=history,
    )

    holdings_by_ticker = new_portfolio.holdings_by_ticker()
    assert set(holdings_by_ticker.keys()) == {"A"}
    assert len(holdings_by_ticker["A"]) == 1
    remaining_lot = holdings_by_ticker["A"][0]
    assert remaining_lot.purchase_date == date(2026, 1, 2)
    assert remaining_lot.quantity == pytest.approx(8.0)

    sell_trades = [t for t in new_portfolio.trades if t.kind == "sell" and t.ticker == "A"]
    assert len(sell_trades) == 1
    assert sell_trades[0].quantity == pytest.approx(10.0)


def test_buy_creates_new_lot_at_trade_date_and_price():
    """Given: existing portfolio and known market price on buy date.

    Example input:
      - Existing holdings: A(2026-01-01, qty=10)
      - Buy ticker: B
      - Trade date: 2026-01-03
      - B price on trade date: 22.0
      - Buy amount: 44.0

    Expected output:
      - New B lot with purchase_date=2026-01-03
      - purchase_price=22.0
      - quantity=2.0
      - Buy trades recorded: 1
    """
    history = _market_history_for_a_and_b()
    portfolio = p.Portfolio(
        date(2026, 1, 2),
        [p.Holding("A", date(2026, 1, 1), 10.0, 10.0, date(2026, 1, 2), 11.0)],
    )

    new_portfolio = portfolio.buy(
        ticker="B",
        amount=44.0,
        trade_date=date(2026, 1, 3),
        prices=history,
    )

    b_lots = [holding for holding in new_portfolio.holdings if holding.ticker == "B"]
    assert len(b_lots) == 1
    new_lot = b_lots[0]
    assert new_lot.purchase_date == date(2026, 1, 3)
    assert new_lot.purchase_price == pytest.approx(22.0)
    assert new_lot.quantity == pytest.approx(2.0)

    buy_trades = [t for t in new_portfolio.trades if t.kind == "buy" and t.ticker == "B"]
    assert len(buy_trades) == 1


def test_trade_preserves_total_value_for_equal_sell_and_buy_amount():
    """Given: same-date trade selling A and buying B for equal amount.

    Example input:
      - Holdings: A(2026-01-01, qty=10), B(2026-01-01, qty=5)
      - Trade date: 2026-01-03
      - A price: 12.0, B price: 22.0
      - Trade amount: 66.0

    Expected output:
      - Total portfolio value unchanged (within float tolerance)
      - A value decreases by 66.0
      - B value increases by 66.0
    """
    history = _market_history_for_a_and_b()
    portfolio = p.Portfolio(
        date(2026, 1, 3),
        [
            p.Holding("A", date(2026, 1, 1), 10.0, 10.0, date(2026, 1, 3), 12.0),
            p.Holding("B", date(2026, 1, 1), 20.0, 5.0, date(2026, 1, 3), 22.0),
        ],
    )

    pre_values = portfolio.value_by_ticker()
    pre_total = portfolio.total_value

    new_portfolio = portfolio.trade(
        sell_ticker="A",
        buy_ticker="B",
        amount=66.0,
        trade_date=date(2026, 1, 3),
        prices=history,
    )

    post_values = new_portfolio.value_by_ticker()
    post_total = new_portfolio.total_value

    assert post_total == pytest.approx(pre_total)
    assert post_values["A"] == pytest.approx(pre_values["A"] - 66.0)
    assert post_values["B"] == pytest.approx(pre_values["B"] + 66.0)


def test_holdings_by_ticker_groups_multiple_lots_under_same_symbol():
    """Given: mixed lots across repeated ticker symbols.

    Example input:
      - Holdings: A(qty=1), B(qty=2), A(qty=3), B(qty=4)
      - Prices: A=10.0, B=20.0

    Expected output:
      - Group keys: A, B
      - Group counts: len(A)=2, len(B)=2
      - Aggregated values: A=40.0, B=120.0
    """
    portfolio = p.Portfolio(
        date(2026, 1, 3),
        [
            p.Holding("A", date(2026, 1, 1), 10.0, 1.0, date(2026, 1, 3), 10.0),
            p.Holding("B", date(2026, 1, 1), 20.0, 2.0, date(2026, 1, 3), 20.0),
            p.Holding("A", date(2026, 1, 2), 10.0, 3.0, date(2026, 1, 3), 10.0),
            p.Holding("B", date(2026, 1, 2), 20.0, 4.0, date(2026, 1, 3), 20.0),
        ],
    )

    grouped = portfolio.holdings_by_ticker()
    values = portfolio.value_by_ticker()

    assert set(grouped.keys()) == {"A", "B"}
    assert len(grouped["A"]) == 2
    assert len(grouped["B"]) == 2
    assert values["A"] == pytest.approx(40.0)
    assert values["B"] == pytest.approx(120.0)


def test__total_value():
    portfolio = p.Portfolio(
        date.today(),
        [
            p.Holding("A", date.today(), 1, 1, date.today(), 1),
            p.Holding("B", date.today(), 2, 2, date.today(), 2),
            p.Holding("C", date.today(), 3, 3, date.today(), 3),
            p.Holding("D", date.today(), 4, 4, date.today(), 4),
        ],
    )

    assert portfolio.total_value == 1 + 4 + 9 + 16


def test__value_by_ticker():
    portfolio = p.Portfolio(
        date.today(),
        [
            p.Holding("A", date.today(), 1, 1, date.today(), 1),
            p.Holding("B", date.today(), 2, 2, date.today(), 2),
            p.Holding("A", date.today(), 3, 3, date.today(), 3),
            p.Holding("B", date.today(), 4, 4, date.today(), 4),
        ],
    )

    values = portfolio.value_by_ticker()

    assert values["A"] == 1 + 9
    assert values["B"] == 4 + 16


def test__trade():
    history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 1.0),
                    d.Price(date(2026, 1, 2), 1.5),
                    d.Price(date(2026, 1, 3), 2.0),
                    d.Price(date(2026, 1, 4), 2.5),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 1, 1), 2.0),
                    d.Price(date(2026, 1, 2), 2.25),
                    d.Price(date(2026, 1, 3), 2.5),
                    d.Price(date(2026, 1, 4), 2.75),
                ],
                [],
            ),
        }
    )
    portfolio = p.Portfolio(
        date.today(),
        [
            p.Holding("A", date(2026, 1, 1), 1.0, 10, date(2026, 1, 1), 1.0),
            p.Holding("A", date(2026, 1, 2), 1.5, 10, date(2026, 1, 2), 1.5),
            p.Holding("B", date(2026, 1, 1), 2.0, 10, date(2026, 1, 1), 2.0),
            p.Holding("B", date(2026, 1, 2), 2.25, 10, date(2026, 1, 2), 2.25),
        ],
    )

    new_portfolio = portfolio.trade(
        sell_ticker="A",
        buy_ticker="B",
        amount=22,
        trade_date=date(2026, 1, 3),
        prices=history,
    )

    values = new_portfolio.value_by_ticker()
    assert values["A"] == 13.5
    assert values["B"] == 64.5

    holdings = new_portfolio.holdings_by_ticker()
    assert len(holdings["A"]) == 1
    assert len(holdings["B"]) == 3

    assert holdings["A"][0].purchase_date == date(2026, 1, 2)
    assert sorted(holdings["B"], key=lambda h: h.purchase_date)[
        -1
    ].purchase_date == date(2026, 1, 3)

    # Sell all of oldest lot of A, oone of 2nd lot of A, buy B.
    assert len(new_portfolio.trades) == 3
