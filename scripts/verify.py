#!/usr/bin/env python3
"""运行 1.0 新树本地检查；通过不等于公司环境与产品全量验收。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"


def run(command: list[str], cwd: Path, title: str) -> None:
    print(f"[CHECK] {title}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-runtime", action="store_true", help="显式运行消耗模型额度的隔离 Runtime 测试")
    parser.add_argument(
        "--live-persona", action="store_true", help="真实短回合、跨 Session 记忆及职责队列测试"
    )
    parser.add_argument("--mysql", action="store_true", help="启动自己的临时 MySQL 验证 schema 和并发")
    parser.add_argument("--live-execution", action="store_true", help="真实工程 Task 与浏览器独立验收")
    args = parser.parse_args()

    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm") or shutil.which("npm")
    if not npm:
        raise RuntimeError("npm not found")
    node = shutil.which("node")
    if not node:
        raise RuntimeError("node not found")

    run([node, str(ROOT / "tests" / "opencode" / "test-superpowers-bootstrap.mjs")], ROOT, "opencode plugin")
    run([node, str(ROOT / "scripts" / "check_openspec_config.mjs")], ROOT, "openspec config")
    run([node, str(ROOT / ".opencode/tools/openspec.mjs"), "validate", "rebuild-astra-1-0"], ROOT, "1.0 spec")
    run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "apps/api",
            "apps/services",
            "agents",
            "domains",
            "migrations",
            "deploy/v1",
            "tests/v1",
            "scripts/verify.py",
        ],
        ROOT,
        "1.0 lint",
    )
    run([sys.executable, "-m", "pytest", "tests/v1", "-q", "--disable-warnings"], ROOT, "1.0 tests")
    run([npm, "run", "build"], WEB, "1.0 web production build")
    os.environ["ASTRA_PYTHON"] = sys.executable
    run([npm, "run", "test:e2e:real"], WEB, "1.0 real API browser E2E")
    if args.live_runtime:
        if not os.environ.get("ASTRA_LIVE_MODEL"):
            parser.error("真实 Runtime 检查必须显式配置 ASTRA_LIVE_MODEL")
        os.environ["ASTRA_LIVE_OPENCODE"] = "1"
        run([sys.executable, "-m", "pytest", "tests/v1/test_runtime_live.py", "-q"], ROOT, "real OpenCode")
    if args.live_persona:
        if not os.environ.get("ASTRA_LIVE_MODEL"):
            parser.error("真实 Persona 检查必须显式配置 ASTRA_LIVE_MODEL")
        os.environ["ASTRA_LIVE_PERSONA"] = "1"
        os.environ["ASTRA_LIVE_CELERY"] = "1"
        run([sys.executable, "-m", "pytest", "tests/v1/test_persona_live.py", "-q"], ROOT, "real Persona")
    if args.mysql:
        run([sys.executable, "tests/v1/run_mysql.py"], ROOT, "isolated MySQL")
    if args.live_execution:
        if not os.environ.get("ASTRA_LIVE_MODEL"):
            parser.error("真实工程检查必须显式配置 ASTRA_LIVE_MODEL")
        os.environ["ASTRA_LIVE_EXECUTION"] = "1"
        os.environ["ASTRA_LIVE_UI"] = "1"
        run([sys.executable, "-m", "pytest", "tests/v1/test_execution_live.py", "-q"], ROOT, "real Task/UI")
    print("1.0 新树本地检查通过；生产迁移、公司部署和完整产品验收仍以验证报告为准。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
