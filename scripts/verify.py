#!/usr/bin/env python3
"""Run Astra's full quality gate."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def run(command: list[str], cwd: Path, title: str) -> None:
    print(f"[CHECK] {title}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    from app.executors.process import local_command

    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found")

    run([sys.executable, "-m", "ruff", "check", "app", "tests"], BACKEND, "backend lint")
    run([sys.executable, "-m", "pytest"], BACKEND, "backend tests")
    run(local_command(npm, ["run", "type-check"]), FRONTEND, "frontend type-check")
    run(local_command(npm, ["run", "build"]), FRONTEND, "frontend production build")
    run([sys.executable, str(ROOT / "scripts" / "e2e.py")], ROOT, "browser E2E")
    print("Astra full verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
