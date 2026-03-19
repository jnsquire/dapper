from __future__ import annotations

from agent_fixture_pkg.scenario import breakpoint_marker
from agent_fixture_pkg.scenario import build_inventory
from agent_fixture_pkg.scenario import choose_focus


def main() -> None:
    inventory = build_inventory()
    focus = choose_focus(inventory)
    report = {
        "inventory": inventory,
        "focus": focus,
        "summary_line": f"{focus}:{inventory['descriptor']}",
    }

    breakpoint_marker("BREAKPOINT: module-report", report)
    print(report)


if __name__ == "__main__":
    main()
