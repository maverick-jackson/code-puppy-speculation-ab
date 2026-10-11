import csv
import io
from typing import List

from .models import Item

REQUIRED = ("sku", "name", "category", "price")


class ParseError(ValueError):
    def __init__(self, line_no: int, message: str):
        super().__init__(f"line {line_no}: {message}")
        self.line_no = line_no


def _to_int(raw: str) -> int:
    return int(raw.strip() or 0)


def _to_float(raw: str) -> float:
    return float(raw.strip())


def _tags(raw: str) -> List[str]:
    return [t.strip() for t in raw.split(";") if t.strip()]


def parse_csv(text: str) -> List[Item]:
    """Parse CSV text with a header row into Items.

    Columns: sku, name, category, price, quantity (optional), tags (optional,
    separated by semicolons).
    """
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise ParseError(1, "missing columns: " + ", ".join(missing))
    items = []
    for line_no, row in enumerate(reader, start=2):
        try:
            items.append(Item(
                sku=row["sku"].strip(),
                name=row["name"].strip(),
                category=row["category"],
                price=_to_float(row["price"]),
                quantity=_to_int(row.get("quantity") or ""),
                tags=_tags(row.get("tags") or ""),
            ))
        except ValueError as exc:
            raise ParseError(line_no, str(exc)) from exc
    return items
