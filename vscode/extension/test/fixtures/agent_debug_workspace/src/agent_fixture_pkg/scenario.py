from __future__ import annotations

RESTOCK_THRESHOLD = 3


def breakpoint_marker(name: str, *values: object) -> None:
    """Provide a stable, searchable line for debugger acceptance fixtures."""


def build_inventory() -> dict[str, object]:
    items = [
        {"name": "alpha", "count": 3},
        {"name": "beta", "count": 5},
        {"name": "gamma", "count": 2},
    ]
    total_count = sum(item["count"] for item in items)
    average_count = total_count / len(items)
    descriptor = f"items={len(items)} total={total_count} average={average_count:.2f}"

    breakpoint_marker("BREAKPOINT: inventory-summary", total_count, average_count, descriptor)
    return {
        "items": items,
        "total_count": total_count,
        "average_count": average_count,
        "descriptor": descriptor,
    }


def choose_focus(inventory: dict[str, object]) -> str:
    counts = [item["count"] for item in inventory["items"]]
    focus = "restock" if min(counts) < RESTOCK_THRESHOLD else "stable"

    breakpoint_marker("BREAKPOINT: focus-decision", counts, focus)
    return focus
