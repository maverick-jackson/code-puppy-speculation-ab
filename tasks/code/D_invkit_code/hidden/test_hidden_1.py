import pytest

from invkit import parse_csv
from invkit.parsing import ParseError

CSV = '''sku,name,category,price,quantity
A1,Anvil,Tools,"1,299.50","1,200"
B2,Bolt,Hardware,0.10," 2,500 "
C3,Clamp,Tools,7.50,12
D4,Dowel,Wood,"12,000",
'''


def test_thousands_separators():
    items = {i.sku: i for i in parse_csv(CSV)}
    assert items["A1"].quantity == 1200
    assert items["A1"].price == pytest.approx(1299.5)
    assert items["B2"].quantity == 2500
    assert items["C3"].quantity == 12
    assert items["D4"].price == pytest.approx(12000.0)
    assert items["D4"].quantity == 0


def test_garbage_still_rejected_with_line_number():
    bad = "sku,name,category,price,quantity\nA1,Anvil,Tools,abc,1\n"
    with pytest.raises(ParseError) as exc:
        parse_csv(bad)
    assert exc.value.line_no == 2


def test_negative_still_rejected():
    bad = 'sku,name,category,price,quantity\nA1,Anvil,Tools,5,"-1,000"\n'
    with pytest.raises(ParseError):
        parse_csv(bad)
