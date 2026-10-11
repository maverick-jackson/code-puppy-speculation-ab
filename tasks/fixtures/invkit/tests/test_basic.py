import pytest

from invkit import Inventory, Item, format_report, parse_csv, price_order

CSV = """sku,name,category,price,quantity,tags
A1,Anvil,Tools,25.00,3,heavy;metal
B2,Bolt,Hardware,0.10,500,
C3,Clamp,Tools,7.50,12,
"""


def test_parse_and_lookup():
    inv = Inventory(parse_csv(CSV))
    assert len(inv) == 3
    assert inv.get("A1").tags == ["heavy", "metal"]
    assert [i.sku for i in inv.by_category("tools")] == ["A1", "C3"]


def test_remove_and_restock():
    inv = Inventory(parse_csv(CSV))
    inv.remove("A1", 2)
    assert inv.get("A1").quantity == 1
    with pytest.raises(ValueError):
        inv.remove("A1", 5)
    inv.restock("A1", 4)
    assert inv.get("A1").quantity == 5


def test_price_small_order():
    inv = Inventory(parse_csv(CSV))
    out = price_order(inv, {"A1": 2}, tax=False)
    assert out["total"] == 50.0 and out["discount"] == 0.0


def test_report_header():
    text = format_report([Item("Z9", "Zip", "Misc", 1.0, 1)])
    assert text.splitlines()[0].startswith("SKU")
