from typing import Dict

from .store import Inventory

BULK_THRESHOLD = 10
BULK_RATE = 0.05
TAX_RATE = 0.07


def bulk_discount(quantity: int, unit_price: float) -> float:
    """Discount (a positive amount) for a single order line."""
    if quantity > BULK_THRESHOLD:
        return round(quantity * unit_price * BULK_RATE, 2)
    return 0.0


def price_order(inventory: Inventory, order: Dict[str, int], tax: bool = True) -> dict:
    """Price an order {sku: quantity}. Does not change stock."""
    lines = []
    subtotal = 0.0
    discount = 0.0
    for sku, qty in sorted(order.items()):
        item = inventory.get(sku)
        if qty > item.quantity:
            raise ValueError(f"only {item.quantity} of {sku} in stock")
        line_total = round(item.price * qty, 2)
        line_discount = bulk_discount(qty, item.price)
        lines.append({"sku": sku, "quantity": qty, "total": line_total, "discount": line_discount})
        subtotal += line_total
        discount += line_discount
    taxable = round(subtotal - discount, 2)
    tax_amount = round(taxable * TAX_RATE, 2) if tax else 0.0
    return {
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "discount": round(discount, 2),
        "tax": tax_amount,
        "total": round(taxable + tax_amount, 2),
    }
