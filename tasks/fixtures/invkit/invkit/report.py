from typing import Iterable, List

from .models import Item

COLUMNS = ("sku", "name", "category", "quantity", "price")
SORT_KEYS = {
    "sku": lambda i: i.sku,
    "name": lambda i: i.name.lower(),
    "quantity": lambda i: i.quantity,
    "price": lambda i: i.price,
    "value": lambda i: i.value,
}


def _row(item: Item) -> List[str]:
    return [item.sku, item.name, item.category, str(item.quantity), f"{item.price:.2f}"]


def format_report(items: Iterable[Item], sort_by: str = "sku") -> str:
    """Render items as a fixed-width text table sorted by `sort_by`."""
    if sort_by not in SORT_KEYS:
        raise ValueError(f"cannot sort by {sort_by!r}; choose from {sorted(SORT_KEYS)}")
    rows = [_row(i) for i in sorted(items, key=SORT_KEYS[sort_by])]
    widths = [len(c) for c in COLUMNS]
    for r in rows:
        widths = [max(w, len(v)) for w, v in zip(widths, r)]
    lines = ["  ".join(c.upper().ljust(w) for c, w in zip(COLUMNS, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for r in rows:
        lines.append("  ".join(v.ljust(w) for v, w in zip(r, widths)).rstrip())
    return "\n".join(lines)
