from datetime import date

from investing import data as d
from investing import history as h
from investing import portfolio as p


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
