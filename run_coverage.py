"""
Coverage runner script for Dapper AI project.
Run tests with coverage reporting.
"""

from pathlib import Path
import subprocess
import sys
import webbrowser


def run_coverage():
    """Run tests with coverage and generate reports."""

    # Run pytest with coverage
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=dapper",
        "--cov-report=term-missing",
        "--cov-report=html",
        "--cov-report=xml",
    ]

    project_dir = Path(__file__).resolve().parent
    result = subprocess.run(cmd, check=False, cwd=str(project_dir))

    if result.returncode == 0:
        # Open HTML report in browser
        html_path = project_dir / "htmlcov" / "index.html"
        if html_path.exists():
            webbrowser.open(f"file://{html_path}")
    else:
        sys.exit(result.returncode)


if __name__ == "__main__":
    run_coverage()
