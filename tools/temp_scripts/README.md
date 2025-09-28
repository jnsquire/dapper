Temporary scripts for local debugging, repros, and small utilities.

Purpose:
- Store throwaway scripts that help reproduce issues or run quick experiments.
- Keep these scripts out of the main package surface.

Guidelines:
- Avoid committing secrets or long-lived credentials.
- Keep scripts short and focused; prefer unit tests for deterministic checks.
- Use `python -m` execution or `./script.py` from the repo root to run.

Examples:
- repro_set_variable.py - quick repro for variable-related handler bugs

This directory is intended for local developer use only. If a script becomes
useful across the team, move it into a proper tools/ or scripts/ location and
add tests or documentation as appropriate.
