#!/usr/bin/env python3
import argparse
import asyncio
import importlib
import platform
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


@dataclass
class CheckResult:
    item: str
    passed: bool
    current: str
    reason: str
    suggestion: str


def result(item: str, passed: bool, current: object, reason: str, suggestion: str) -> CheckResult:
    return CheckResult(item, passed, str(current), reason, suggestion)


def check_python() -> CheckResult:
    version = platform.python_version()
    passed = sys.version_info >= (3, 11)
    return result(
        "Python 版本",
        passed,
        f"{sys.executable} ({version})",
        "版本满足项目要求" if passed else "Astra 当前代码基线需要 Python 3.11+",
        "无需处理" if passed else "使用 Python 3.11 或更高版本重建 .venv",
    )


def check_operating_system() -> CheckResult:
    current = f"{platform.system()} {platform.release()} ({platform.machine()})"
    return result("当前操作系统", True, current, "已识别运行平台", "无需处理")


def check_dependencies() -> CheckResult:
    modules = {
        "alembic": "alembic",
        "asyncmy": "asyncmy",
        "celery": "celery",
        "fastapi": "fastapi",
        "paramiko": "paramiko",
        "redis": "redis",
        "sqlalchemy": "sqlalchemy",
        "uvicorn": "uvicorn",
    }
    missing = []
    for label, module in modules.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(label)
    return result(
        "Python 必要依赖",
        not missing,
        "已安装" if not missing else f"缺少: {', '.join(missing)}",
        "依赖完整" if not missing else "当前解释器未安装全部后端依赖",
        "无需处理" if not missing else "执行 python -m pip install -e backend",
    )


def check_writable_directory(item: str, path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".astra-check-", dir=path, delete=False) as probe:
            probe_path = Path(probe.name)
            probe.write(b"ok")
        probe_path.unlink()
        return result(item, True, path, "目录存在且可写", "无需处理")
    except OSError as exc:
        return result(
            item,
            False,
            path,
            str(exc),
            "创建该目录，并给 Astra 运行账号读写权限",
        )


async def check_database(settings) -> list[CheckResult]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import create_async_engine

    checks = []
    engine_options = {"pool_pre_ping": True}
    if settings.sqlalchemy_database_url.startswith("mysql"):
        engine_options["pool_recycle"] = settings.database_pool_recycle
    engine = None
    try:
        engine = create_async_engine(settings.sqlalchemy_database_url, **engine_options)
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            checks.append(
                result("数据库连接", True, settings.database_description, "连接成功", "无需处理")
            )

            if settings.sqlalchemy_database_url.startswith("mysql"):
                row = (
                    await connection.execute(
                        text(
                            "SELECT @@version, @@character_set_database, "
                            "@@character_set_connection, @@collation_database"
                        )
                    )
                ).one()
                charset_ok = all(str(value).lower() == "utf8mb4" for value in row[1:3])
                checks.append(
                    result(
                        "MySQL 字符集",
                        charset_ok,
                        f"MySQL {row[0]} / database={row[1]} / connection={row[2]} / {row[3]}",
                        "数据库与连接字符集均为 utf8mb4"
                        if charset_ok
                        else "数据库或连接字符集不是 utf8mb4",
                        "无需处理"
                        if charset_ok
                        else "将 Astra 数据库和连接字符集调整为 utf8mb4",
                    )
                )

            def schema_state(sync_connection):
                inspector = inspect(sync_connection)
                tables = set(inspector.get_table_names())
                version = None
                if "alembic_version" in tables:
                    version = sync_connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one_or_none()
                return tables, version

            tables, current_revision = await connection.run_sync(schema_state)
            config = Config(str(BACKEND_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
            head_revision = ScriptDirectory.from_config(config).get_current_head()
            required_tables = {
                "digital_employees",
                "events",
                "opencode_execution_environments",
                "runs",
                "task_categories",
                "tasks",
            }
            missing_tables = sorted(required_tables - tables)
            migration_ok = not missing_tables and current_revision == head_revision
            checks.append(
                result(
                    "数据库表与迁移",
                    migration_ok,
                    f"revision={current_revision or '未初始化'}, tables={len(tables)}",
                    "表结构与迁移已到最新"
                    if migration_ok
                    else f"缺少表: {missing_tables or '无'}; head={head_revision}",
                    "无需处理"
                    if migration_ok
                    else "在 backend 目录执行 python -m alembic upgrade head",
                )
            )
    except Exception as exc:  # noqa: BLE001 - convert driver errors into actionable checks
        detail = str(exc).replace(
            settings.sqlalchemy_database_url, settings.database_description
        )
        checks.append(
            result(
                "数据库连接",
                False,
                settings.database_description,
                detail,
                "检查 MySQL 服务、Host、Port、Database、Username、Password 和网络权限",
            )
        )
        checks.append(
            result(
                "数据库表与迁移",
                False,
                "未检查",
                "数据库连接失败",
                "数据库连接恢复后执行 python -m alembic upgrade head",
            )
        )
    finally:
        if engine is not None:
            await engine.dispose()
    return checks


async def check_redis(settings) -> CheckResult:
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return result(
            "Redis 连接", True, settings.redis_description, "连接成功", "无需处理"
        )
    except Exception as exc:  # noqa: BLE001 - Redis clients expose multiple error types
        return result(
            "Redis 连接",
            False,
            settings.redis_description,
            str(exc).replace(settings.redis_url, settings.redis_description),
            "检查 ASTRA_REDIS_URL 及 Redis 服务；Windows 可连接公司统一 Redis",
        )


async def check_agent(settings) -> CheckResult:
    from app.executors.process import (
        local_command,
        process_group_options,
        resolve_executable,
        terminate_process,
    )

    resolved = resolve_executable(settings.opencode_binary)
    if not resolved:
        return result(
            "默认 Agent 可执行文件",
            False,
            settings.opencode_binary,
            "PATH 和配置路径中都未找到可执行文件",
            "设置 ASTRA_OPENCODE_BINARY 为 opencode.exe 绝对路径，或将 OpenCode 加入 PATH",
        )
    try:
        process = await asyncio.create_subprocess_exec(
            *local_command(resolved, ["--version"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **process_group_options(),
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=15)
        except TimeoutError:
            await terminate_process(process)
            return result(
                "默认 Agent 可执行文件",
                False,
                resolved,
                "执行 --version 超过 15 秒",
                "确认 Agent 能在当前账号下非交互启动，并检查模型配置或网络",
            )
        detail = output.decode("utf-8", errors="replace").strip()[:500]
        passed = process.returncode == 0
        return result(
            "默认 Agent 可执行文件",
            passed,
            resolved,
            detail or f"退出码 {process.returncode}",
            "无需处理" if passed else "确认该文件可执行且 --version 能正常返回",
        )
    except Exception as exc:  # noqa: BLE001 - process launch errors vary by operating system
        return result(
            "默认 Agent 可执行文件",
            False,
            resolved,
            str(exc),
            "确认路径无误，并允许 Astra 运行账号启动该程序",
        )


def print_results(checks: list[CheckResult]) -> None:
    for check in checks:
        marker = "PASS" if check.passed else "FAIL"
        print(f"[{marker}] {check.item}")
        print(f"  当前值: {check.current}")
        print(f"  原因: {check.reason}")
        print(f"  建议: {check.suggestion}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Astra 跨平台环境自检")
    parser.parse_args()

    checks = [check_operating_system(), check_python(), check_dependencies()]
    if not checks[-1].passed:
        print_results(checks)
        return 1

    from app.config.settings import PROJECT_ROOT, get_settings

    try:
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - present invalid settings without traceback
        if hasattr(exc, "errors"):
            details = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                for error in exc.errors(include_input=False)
            )
        else:
            details = exc.__class__.__name__
        checks.append(
            result(
                "Astra 配置",
                False,
                PROJECT_ROOT / ".env",
                details,
                "检查 .env 的变量名称、格式和值；可重新复制 deploy 中的示例",
            )
        )
        print_results(checks)
        return 1
    checks.extend(
        [
            check_writable_directory("Astra Workspace 目录", settings.resolved_workspace_root),
            check_writable_directory("日志目录", settings.resolved_log_dir),
            check_writable_directory("运行状态目录", settings.resolved_runtime_dir),
            await check_agent(settings),
            await check_redis(settings),
        ]
    )
    checks.extend(await check_database(settings))
    print_results(checks)
    failures = sum(not check.passed for check in checks)
    print(f"\n自检完成：{len(checks) - failures} 项通过，{failures} 项失败。")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
