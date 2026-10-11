import pytest

from invkit import Inventory, Item, parse_csv
from invkit.cli import main

CSV = """sku,name,category,price,quantity
A1,Anvil,Tools,25.00,3
B2,Bolt,Hardware,0.10,505
C3,Clamp, tools ,7.25,12
D4,Drill,Power,99.99,0
"""


def inv():
    return Inventory(parse_csv(CSV))


def test_total_value_all():
    assert inv().total_value() == pytest.approx(75.0 + 50.5 + 87.0)


def test_total_value_by_category_case_insensitive():
    assert inv().total_value("TOOLS") == pytest.approx(162.0)
    assert inv().total_value(" hardware ") == pytest.approx(50.5)


def test_total_value_empty_and_unknown():
    assert Inventory().total_value() == 0
    assert inv().total_value("garden") == 0


def test_total_value_rounded():
    i = Inventory([Item("X", "x", "c", 0.1, 3)])
    assert i.total_value() == 0.3


def test_cli_total_flag(tmp_path, capsys):
    p = tmp_path / "inv.csv"
    p.write_text(CSV)
    assert main([str(p), "--total"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "Total value: 212.50"


def test_cli_without_flag_has_no_total(tmp_path, capsys):
    p = tmp_path / "inv.csv"
    p.write_text(CSV)
    main([str(p)])
    assert "Total value" not in capsys.readouterr().out
