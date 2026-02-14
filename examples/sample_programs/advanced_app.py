"""
Advanced Python application for testing debug adapter with complex scenarios.

This program demonstrates more advanced Python constructs that test
debugging functionality including classes, async code, generators, and
more complex data structures.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import json
import logging
import threading
import time
from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)


@dataclass
class Person:
    """Simple dataclass for testing object inspection."""

    name: str
    age: int
    email: str

    # Constants
    ADULT_AGE = 18

    def __post_init__(self):
        if self.age < 0:
            msg = "Age cannot be negative"
            raise ValueError(msg)

    def get_info(self) -> dict[str, Any]:
        """Get person information as a dictionary."""
        return {
            "name": self.name,
            "age": self.age,
            "email": self.email,
            "is_adult": self.age >= self.ADULT_AGE,
        }


class DataProcessor:
    """Class for processing data with various methods."""

    # Constants
    MAX_FACTORIAL_INPUT = 10

    def __init__(self):
        self.data_cache = defaultdict(list)
        self.processing_count = 0

    def add_data(self, category: str, items: list[Any]) -> None:
        """Add data to the processor."""
        self.data_cache[category].extend(items)
        self.processing_count += len(items)

    def get_statistics(self) -> dict[str, Any]:
        """Get processing statistics."""
        total_items = sum(len(items) for items in self.data_cache.values())
        return {
            "categories": len(self.data_cache),
            "total_items": total_items,
            "processing_count": self.processing_count,
            "average_per_category": total_items / len(self.data_cache) if self.data_cache else 0,
        }

    def process_numbers(self, numbers: list[int]) -> Generator[dict[str, Any], None, None]:
        """Generator that yields processing results."""
        for i, num in enumerate(numbers):
            # Simulate some processing time
            time.sleep(0.1)

            result = {
                "index": i,
                "original": num,
                "squared": num**2,
                "is_even": num % 2 == 0,
                "factorial": (
                    self._factorial(num) if num <= self.MAX_FACTORIAL_INPUT else "too_large"
                ),
            }
            yield result

    def _factorial(self, n: int) -> int:
        """Calculate factorial recursively."""
        if n <= 1:
            return 1
        return n * self._factorial(n - 1)


async def async_data_fetcher(delay: float, data_id: str) -> dict[str, Any]:
    """Simulate async data fetching."""
    logger.info(f"Fetching data {data_id}...")
    await asyncio.sleep(delay)

    return {
        "id": data_id,
        "timestamp": time.time(),
        "delay": delay,
        "status": "success",
    }


async def process_async_data() -> list[dict[str, Any]]:
    """Process multiple async data requests."""
    tasks = [
        async_data_fetcher(0.5, "data_1"),
        async_data_fetcher(0.3, "data_2"),
        async_data_fetcher(0.7, "data_3"),
    ]

    # Gather all results
    results = await asyncio.gather(*tasks)

    # Process results
    processed_results = []
    for result in results:
        processed_result = {
            **result,
            "processed_at": time.time(),
            "duration": result["delay"],
        }
        processed_results.append(processed_result)

    return processed_results


def threaded_worker(worker_id: int, shared_data: dict[str, Any], lock: threading.Lock) -> None:
    """Worker function for threading example."""
    for i in range(5):
        time.sleep(0.2)

        with lock:
            if "counters" not in shared_data:
                shared_data["counters"] = {}
            if worker_id not in shared_data["counters"]:
                shared_data["counters"][worker_id] = 0

            shared_data["counters"][worker_id] += 1
            logger.info(
                f"Worker {worker_id}: iteration {i + 1}, total count: {shared_data['counters'][worker_id]}"
            )


def demonstrate_threading():
    """Demonstrate multi-threading for debugging."""
    logger.info("=== Threading Demo ===")

    shared_data = {"start_time": time.time()}
    lock = threading.Lock()

    # Create and start threads
    threads = []
    for worker_id in range(3):
        thread = threading.Thread(target=threaded_worker, args=(worker_id, shared_data, lock))
        threads.append(thread)
        thread.start()

    # Wait for all threads to complete
    for thread in threads:
        thread.join()

    shared_data["end_time"] = time.time()
    shared_data["duration"] = shared_data["end_time"] - shared_data["start_time"]

    logger.info(f"Threading completed: {shared_data}")
    return shared_data


async def main_async():
    """Main async function demonstrating various debugging scenarios."""
    logger.info("=== Advanced Debug Test (Async) ===")

    # Test dataclass and object creation
    people = [
        Person("Alice", 30, "alice@example.com"),
        Person("Bob", 25, "bob@example.com"),
        Person("Charlie", 35, "charlie@example.com"),
    ]

    logger.info("People created:")
    for person in people:
        info = person.get_info()
        logger.info(f"  {json.dumps(info, indent=2)}")

    # Test data processor
    processor = DataProcessor()
    processor.add_data("numbers", [1, 2, 3, 4, 5])
    processor.add_data("letters", ["a", "b", "c"])

    stats = processor.get_statistics()
    logger.info(f"Processor stats: {stats}")

    # Test generator
    logger.info("Processing numbers with generator:")
    for result in processor.process_numbers([3, 4, 5]):
        logger.info(f"  Generated: {result}")

    # Test async functionality
    logger.info("Processing async data...")
    async_results = await process_async_data()
    logger.info("Async results:")
    for result in async_results:
        logger.info(f"  {json.dumps(result, indent=2)}")

    logger.info("=== Async App completed ===")


def main():
    """Main synchronous function."""
    logger.info("=== Advanced Debug Test (Sync) ===")

    # Run threading demo
    threading_results = demonstrate_threading()

    # Create a complex data structure
    complex_data = {
        "metadata": {
            "version": "1.0",
            "created_at": time.time(),
            "features": ["debugging", "testing", "examples"],
        },
        "threading_results": threading_results,
        "nested": {
            "level1": {
                "level2": {
                    "level3": {
                        "deep_value": "found_me",
                        "numbers": list(range(10)),
                    }
                }
            }
        },
    }

    logger.info(f"Complex data structure created with {len(str(complex_data))} characters")

    # Test exception handling with custom exception
    try:
        # This will trigger an exception
        Person("Invalid", -5, "test@example.com")
    except ValueError as e:
        logger.info(f"Caught expected exception: {e}")

    logger.info("=== Sync App completed ===")

    # Run async part
    logger.info("Starting async portion...")
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
