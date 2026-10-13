"""启动自己的临时 MySQL；绝不读取系统配置或连接现有数据库。"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]


async def wait_for_mysql(url):
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        for _ in range(120):
            try:
                async with engine.connect() as connection:
                    return await connection.scalar(text("SELECT VERSION()"))
            except Exception:
                await asyncio.sleep(0.25)
        raise RuntimeError("独立 MySQL 未就绪，请检查测试实例日志")
    finally:
        await engine.dispose()


async def create_schema(url, name):
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    finally:
        await engine.dispose()


def main():
    binary = shutil.which("mysqld")
    if not binary:
        raise RuntimeError("需先配置本机 mysqld；此入口不会联网安装或接管现有 MySQL")
    report = {
        "kind": "isolated_mysql_integration",
        "started_at": time.time(),
        "result": "FAILED",
        "whole_system_acceptance": False,
        "existing_database_touched": False,
    }
    report_path = ROOT / "docs/astra-1.0/mysql-live-report.json"
    process = None
    with tempfile.TemporaryDirectory(prefix="astra-v1-mysql-") as temporary:
        directory = Path(temporary)
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        try:
            subprocess.run(
                [
                    binary,
                    "--no-defaults",
                    "--initialize-insecure",
                    f"--datadir={directory / 'data'}",
                    f"--log-error={directory / 'initialize.log'}",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            process = subprocess.Popen(
                [
                    binary,
                    "--no-defaults",
                    f"--datadir={directory / 'data'}",
                    "--bind-address=127.0.0.1",
                    f"--port={port}",
                    f"--socket={directory / 'mysql.sock'}",
                    "--mysqlx=OFF",
                    "--skip-log-bin",
                    "--innodb-lock-wait-timeout=2",
                    f"--pid-file={directory / 'mysql.pid'}",
                    f"--log-error={directory / 'server.log'}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            server_url = f"mysql+asyncmy://root@127.0.0.1:{port}"
            report["server_version"] = asyncio.run(wait_for_mysql(server_url))
            schema = "astra_v1_test_schema_" + uuid4().hex
            asyncio.run(create_schema(server_url, schema))
            env = {**os.environ, "ASTRA_V1_DATABASE_URL": f"{server_url}/{schema}"}
            subprocess.run(
                [sys.executable, "-m", "apps.api.manage", "migrate"], cwd=ROOT, env=env, check=True
            )
            report["static_schema_migrated"] = True
            env["ASTRA_V1_TEST_MYSQL_SERVER"] = server_url
            files = [
                "test_domains.py",
                "test_dispatch.py",
                "test_review_regressions.py",
                "test_routines.py",
                "test_handoff_responses.py",
                "test_history.py",
                "test_tools.py",
                "test_identity_management.py",
                "test_mysql_locking.py",
                "test_memory.py",
                "test_personas.py",
                "test_sse.py",
                "test_executions.py",
                "test_persona_reviews.py",
            ]
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "--disable-warnings",
                    *[f"tests/v1/{name}" for name in files],
                ],
                cwd=ROOT,
                env=env,
            )
            report["test_files"] = files
            report["test_exit_code"] = result.returncode
            report["result"] = "PASSED" if result.returncode == 0 else "FAILED"
            return result.returncode
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            report["finished_at"] = time.time()
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
