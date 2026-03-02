"""
Loop-focused example program for debugger demonstrations.

This script is intentionally small and easy to step through.  It contains
several looping constructs and variables that are ideal for setting
expression breakpoints (e.g. `i`, `total`, `x`).  Use it when you need a
concise repro for logic inside loops or when you want to demonstrate how
the debugger handles conditional and expression breakpoints.

Typical scenarios:

* Set a breakpoint on the line marked with `# BREAKPOINT` and use a condition
  such as `i == 3` or `total > 5`.
* Try an expression-only breakpoint like `x == 2` in the `while` loop.
* Step through the loops one iteration at a time and inspect `i`, `total`,
  `item`, and `x`.

To run the example:

```bash
python examples/sample_programs/loop_example.py
```

`"""

from __future__ import annotations


def compute_sum(n: int) -> int:
    """Return the sum of all integers in ``range(n)``.

    This function contains a simple ``for`` loop that makes it easy to set
    conditional or expression breakpoints.  The comment on the accumulator
    update is a convenient place to put a breakpoint when learning how expression
    conditions work.
    """

    total = 0
    for i in range(n):
        # BREAKPOINT: try condition ``i == 3`` or ``total > 5``
        total += i
    return total


def main() -> None:
    print("=== Loop Example ===")

    # run the for-loop helper twice with different limits
    for limit in (5, 10):
        result = compute_sum(limit)
        print(f"sum up to {limit - 1} = {result}")

    # a simple while loop variant
    x = 0
    while x < 4:  # noqa: PLR2004
        # BREAKPOINT: expression breakpoint like ``x == 2`` works here
        print("while loop iteration", x)
        x += 1

    print("example complete")


if __name__ == "__main__":
    main()
