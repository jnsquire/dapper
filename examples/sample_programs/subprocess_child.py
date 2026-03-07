from __future__ import annotations

import os
import time


def compute_values(seed: int) -> dict[str, int]:
    total = seed
    for offset in range(3):
        total += offset
    return {
        "seed": seed,
        "total": total,
        "pid": os.getpid(),
    }


def main() -> None:
    child_pid = os.getpid()
    print(f"[child] pid={child_pid}", flush=True)

    payload = compute_values(7)  # BREAKPOINT: child entry
    print(f"[child] payload={payload}", flush=True)

    time.sleep(0.2)
    print("[child] done", flush=True)


if __name__ == "__main__":
    main()
