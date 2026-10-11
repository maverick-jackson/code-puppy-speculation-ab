from dataclasses import dataclass, field


@dataclass
class Item:
    sku: str
    name: str
    category: str
    price: float
    quantity: int = 0
    tags: list = field(default_factory=list)

    def __post_init__(self):
        if self.price < 0:
            raise ValueError(f"negative price for {self.sku}")
        if self.quantity < 0:
            raise ValueError(f"negative quantity for {self.sku}")
        self.category = self.category.strip()

    @property
    def value(self) -> float:
        return self.price * self.quantity
