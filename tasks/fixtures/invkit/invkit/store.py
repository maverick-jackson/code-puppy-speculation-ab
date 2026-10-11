from typing import Dict, Iterable, List, Optional

from .models import Item


class DuplicateSku(KeyError):
    pass


class Inventory:
    """In-memory collection of items keyed by SKU."""

    def __init__(self, items: Optional[Iterable[Item]] = None):
        self._items: Dict[str, Item] = {}
        for item in items or []:
            self.add(item)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items.values())

    def add(self, item: Item) -> None:
        if item.sku in self._items:
            raise DuplicateSku(item.sku)
        self._items[item.sku] = item

    def get(self, sku: str) -> Item:
        return self._items[sku]

    def remove(self, sku: str, quantity: int) -> Item:
        item = self._items[sku]
        if quantity > item.quantity:
            raise ValueError(f"only {item.quantity} of {sku} in stock")
        item.quantity -= quantity
        return item

    def restock(self, sku: str, quantity: int) -> Item:
        if quantity <= 0:
            raise ValueError("restock quantity must be positive")
        item = self._items[sku]
        item.quantity += quantity
        return item

    def by_category(self, category: str) -> List[Item]:
        want = category.strip().lower()
        return [i for i in self._items.values() if i.category.lower() == want]

    def low_stock(self, threshold: int = 5) -> List[Item]:
        return sorted((i for i in self._items.values() if i.quantity < threshold),
                      key=lambda i: (i.quantity, i.sku))
