from __future__ import annotations

from dataclasses import dataclass

LOYALTY_DISCOUNT_THRESHOLD = 100
REVIEW_TOTAL_THRESHOLD = 20


def breakpoint_marker(name: str, *values: object) -> None:
    """Provide a stable, searchable line for debugger acceptance fixtures."""


@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price: float

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.unit_price, 2)


class CheckoutSession:
    def __init__(self, customer: str, loyalty_points: int) -> None:
        self.customer = customer
        self.loyalty_points = loyalty_points
        self.lines: list[OrderLine] = []

    def add_line(self, sku: str, quantity: int, unit_price: float) -> None:
        self.lines.append(OrderLine(sku=sku, quantity=quantity, unit_price=unit_price))

    def summary(self) -> dict[str, object]:
        subtotal = round(sum(line.line_total for line in self.lines), 2)
        discount_rate = 0.10 if self.loyalty_points >= LOYALTY_DISCOUNT_THRESHOLD else 0.0
        discounted_subtotal = round(subtotal * (1 - discount_rate), 2)
        tax = round(discounted_subtotal * 0.08, 2)
        total = round(discounted_subtotal + tax, 2)
        status = "review" if total >= REVIEW_TOTAL_THRESHOLD else "clear"

        breakpoint_marker("BREAKPOINT: order-summary", subtotal, discount_rate, total, status)
        return {
            "customer": self.customer,
            "subtotal": subtotal,
            "discount_rate": discount_rate,
            "discounted_subtotal": discounted_subtotal,
            "tax": tax,
            "total": total,
            "status": status,
            "item_count": len(self.lines),
        }


def build_session() -> CheckoutSession:
    session = CheckoutSession(customer="Ada", loyalty_points=120)
    session.add_line("tea", 2, 3.50)
    session.add_line("cake", 1, 6.25)
    session.add_line("jam", 3, 2.00)
    return session


def main() -> None:
    session = build_session()
    summary = session.summary()
    threshold = 15
    needs_follow_up = summary["total"] > threshold

    breakpoint_marker("BREAKPOINT: main-after-summary", summary, threshold, needs_follow_up)
    print(
        {
            "summary": summary,
            "needs_follow_up": needs_follow_up,
            "threshold": threshold,
        }
    )


if __name__ == "__main__":
    main()
