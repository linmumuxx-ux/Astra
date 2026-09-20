#!/usr/bin/env python3
"""Archive legacy Run-era facts before destructive Astra schema upgrades.

This tool is intentionally one-way and offline. It does not restore the old Run
runtime model; it preserves historical rows and Task.result for audit/analysis
before migrations 0024/0025 remove them.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

LEGACY_TABLES = (
    "runs",
    "tool_usages",
    "evidence",
    "task_sessions",
    "session_messages",
    "run_inquiries",
    "run_dispatch_outbox",
)


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    return str(value)


def _snapshot(sync_connection) -> dict[str, Any]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    metadata = MetaData()
    payload: dict[str, Any] = {
        "schema_version": None,
        "legacy_tables": {},
        "task_results": [],
    }
    if "alembic_version" in tables:
        payload["schema_version"] = sync_connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()

    for name in LEGACY_TABLES:
        if name not in tables:
            continue
        table = Table(name, metadata, autoload_with=sync_connection)
        rows = [dict(row) for row in sync_connection.execute(select(table)).mappings()]
        payload["legacy_tables"][name] = rows

    if "tasks" in tables:
        columns = {item["name"] for item in inspector.get_columns("tasks")}
        if "result" in columns:
            tasks = Table("tasks", metadata, autoload_with=sync_connection)
            rows = sync_connection.execute(
                select(tasks.c.id, tasks.c.status, tasks.c.result).where(tasks.c.result.is_not(None))
            ).mappings()
            payload["task_results"] = [dict(row) for row in rows]
    return payload


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="归档 Astra 旧 Run/ToolUsage/Evidence/Task.result 历史数据"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / ".astra" / "legacy-history.json",
        help="归档文件路径",
    )
    args = parser.parse_args()

    from app.config.settings import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            payload = await connection.run_sync(_snapshot)
    finally:
        await engine.dispose()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
    args.output.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()

    counts = {
        name: len(rows)
        for name, rows in payload["legacy_tables"].items()
    }
    manifest = {
        "archive": str(args.output),
        "sha256": digest,
        "schema_version": payload["schema_version"],
        "legacy_table_counts": counts,
        "task_result_count": len(payload["task_results"]),
        "total_legacy_rows": sum(counts.values()) + len(payload["task_results"]),
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
