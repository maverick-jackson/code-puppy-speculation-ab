import pytest

from invkit import Inventory, Item, price_order
from invkit.pricing import bulk_discount


def inv():
    return Inventory([Item("A", "a", "c", 2.0, 100), Item("B", "b", "c", 3.0, 100)])


def test_exactly_threshold_gets_discount():
    assert bulk_discount(10, 2.0) == pytest.approx(1.0)


def test_below_threshold_no_discount():
    assert bulk_discount(9, 2.0) == 0.0


def test_above_threshold():
    assert bulk_discount(20, 3.0) == pytest.approx(3.0)


def test_order_totals():
    out = price_order(inv(), {"A": 10, "B": 9}, tax=False)
    assert out["subtotal"] == pytest.approx(47.0)
    assert out["discount"] == pytest.approx(1.0)
    assert out["total"] == pytest.approx(46.0)
    out = price_order(inv(), {"A": 10}, tax=True)
    assert out["tax"] == pytest.approx(1.33)
    assert out["total"] == pytest.approx(20.33)
