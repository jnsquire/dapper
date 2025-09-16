"""
Simple Python application for testing the debug adapter.

This program demonstrates basic Python constructs that are useful for testing
debugging functionality like breakpoints, variable inspection, and stepping.
"""

from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)


def calculate_fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number recursively."""
    if n <= 1:
        return n
    return calculate_fibonacci(n - 1) + calculate_fibonacci(n - 2)


def process_numbers(numbers: list[int]) -> dict[str, float]:
    """Process a list of numbers and return statistics."""
    if not numbers:
        return {"count": 0, "sum": 0, "average": 0, "max": 0, "min": 0}

    total = sum(numbers)
    count = len(numbers)
    average = total / count

    return {
        "count": count,
        "sum": total,
        "average": average,
        "max": max(numbers),
        "min": min(numbers),
    }


def simulate_work(duration: float = 1.0) -> str:
    """Simulate some work with a delay."""
    logger.info(f"Starting work that will take {duration} seconds...")

    # Set a breakpoint here to test debugging during sleep
    time.sleep(duration)

    logger.info(f"Work completed after {duration} seconds")
    return f"Work completed after {duration} seconds"


def demonstrate_exception_handling():
    """Demonstrate exception handling for debugging."""
    try:
        # This will cause a division by zero error
        return 10 / 0
    except ZeroDivisionError as e:
        logger.info(f"Caught exception: {e}")
        return None


def main():
    """Main function to demonstrate various debugging scenarios."""
    logger.info("=== Simple App Debug Test ===")

    # Test basic variables
    name = "Debug Test"
    version = 1.0
    logger.info(f"{name} v{version}")

    # Test list processing
    test_numbers = [1, 5, 3, 9, 2, 8, 4]
    logger.info(f"Original numbers: {test_numbers}")

    stats = process_numbers(test_numbers)
    logger.info(f"Statistics: {stats}")

    # Test recursive function
    fib_n = 8
    fib_result = calculate_fibonacci(fib_n)
    logger.info(f"Fibonacci({fib_n}) = {fib_result}")

    # Test with random numbers
    random_numbers = [random.randint(1, 100) for _ in range(5)]
    logger.info(f"Random numbers: {random_numbers}")
    random_stats = process_numbers(random_numbers)
    logger.info(f"Random stats: {random_stats}")

    # Test simulated work
    work_result = simulate_work(0.5)
    logger.info(f"Work result: {work_result}")

    # Test exception handling
    exception_result = demonstrate_exception_handling()
    logger.info(f"Exception handling result: {exception_result}")

    logger.info("=== App completed ===")


if __name__ == "__main__":
    main()
