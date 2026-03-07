from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time


def build_child_command() -> list[str]:
    child_script = Path(__file__).with_name("subprocess_child.py")
    return [sys.executable, str(child_script)]


def main() -> None:
    command = build_child_command()
    print(f"[parent] spawning child: {command}", flush=True)

    child = subprocess.Popen(command)  # BREAKPOINT: parent before child starts
    print(f"[parent] child pid={child.pid}", flush=True)

    status = {"spawned": True, "childPid": child.pid}
    print(f"[parent] status={status}", flush=True)  # BREAKPOINT: parent after spawn

    exit_code = child.wait()
    print(f"[parent] child exit={exit_code}", flush=True)

    time.sleep(0.2)
    print("[parent] done", flush=True)


if __name__ == "__main__":
    main()
