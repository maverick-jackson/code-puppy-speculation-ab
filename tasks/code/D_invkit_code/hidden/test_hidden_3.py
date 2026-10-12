from invkit import Item, format_report
from invkit.cli import main

ITEMS = [Item("B2", "bolt", "hw", 0.1, 500), Item("A1", "Anvil", "tools", 25.0, 3),
         Item("C3", "clamp", "tools", 7.5, 12)]


def skus(text):
    return [ln.split()[0] for ln in text.splitlines()[2:]]


def test_default_ascending_unchanged():
    assert skus(format_report(ITEMS)) == ["A1", "B2", "C3"]
    assert skus(format_report(ITEMS, sort_by="price")) == ["B2", "C3", "A1"]


def test_descending_keyword():
    assert skus(format_report(ITEMS, descending=True)) == ["C3", "B2", "A1"]
    assert skus(format_report(ITEMS, sort_by="quantity", descending=True)) == ["B2", "C3", "A1"]
    assert skus(format_report(ITEMS, sort_by="name", descending=True)) == ["C3", "B2", "A1"]


def test_cli_desc_flag(tmp_path, capsys):
    p = tmp_path / "i.csv"
    p.write_text("sku,name,category,price,quantity\nB2,bolt,hw,0.1,500\nA1,Anvil,tools,25,3\n")
    assert main([str(p), "--sort", "price", "--desc"]) == 0
    assert skus(capsys.readouterr().out) == ["A1", "B2"]


def test_cli_default_ascending(tmp_path, capsys):
    p = tmp_path / "i.csv"
    p.write_text("sku,name,category,price,quantity\nB2,bolt,hw,0.1,500\nA1,Anvil,tools,25,3\n")
    main([str(p), "--sort", "price"])
    assert skus(capsys.readouterr().out) == ["B2", "A1"]
