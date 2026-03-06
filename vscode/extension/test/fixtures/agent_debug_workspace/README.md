# Agent Debug Fixture Workspace

This workspace is a deterministic target for agent-layer testing of the Dapper tools.

## Files

- `app.py`: file launch target with predictable order-summary locals.
- `src/agent_fixture_pkg/__main__.py`: module launch target.
- `src/agent_fixture_pkg/scenario.py`: helper module with predictable inventory data.
- `.vscode/launch.template.json`: ready-made Dapper launch configurations that can be copied into `launch.json` when the fixture folder is opened as its own workspace.

## Breakpoint Markers

Use the source marker strings to discover exact line numbers before setting breakpoints.

- `BREAKPOINT: order-summary`
- `BREAKPOINT: main-after-summary`
- `BREAKPOINT: inventory-summary`
- `BREAKPOINT: focus-decision`
- `BREAKPOINT: module-report`

## Expected Values

### File Launch

At `BREAKPOINT: order-summary` in `app.py`:

- `subtotal == 19.25`
- `discount_rate == 0.10`
- `discounted_subtotal == 17.32`
- `tax == 1.39`
- `total == 18.71`
- `status == "clear"`

At `BREAKPOINT: main-after-summary` in `app.py`:

- `summary["total"] == 18.71`
- `needs_follow_up is True`
- `threshold == 15`

### Module Launch

At `BREAKPOINT: inventory-summary` in `src/agent_fixture_pkg/scenario.py`:

- `total_count == 10`
- `average_count == 10 / 3`
- `descriptor == "items=3 total=10 average=3.33"`

At `BREAKPOINT: focus-decision` in `src/agent_fixture_pkg/scenario.py`:

- `counts == [3, 5, 2]`
- `focus == "restock"`

At `BREAKPOINT: module-report` in `src/agent_fixture_pkg/__main__.py`:

- `report["focus"] == "restock"`
- `report["summary_line"] == "restock:items=3 total=10 average=3.33"`
