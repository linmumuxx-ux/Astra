"""python -m migrations.from_0xx；连接地址只从环境变量读取。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .etl import (
    MigrationError,
    build_plan,
    export_bundle,
    import_staging,
    read_json,
    reconcile,
    rollback_staging,
    write_json,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Astra 0.xx 一次性离线迁移；当前目标为隔离 staging")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="只读全表导出；必须提供人工冻结声明")
    export.add_argument("--source-env", default="ASTRA_0XX_DATABASE_URL")
    export.add_argument("--freeze", type=Path, required=True)
    export.add_argument("--source-commit", required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--dry-run", action="store_true")
    plan = commands.add_parser("map", help="验证导出哈希并执行显式映射")
    plan.add_argument("--bundle", type=Path, required=True)
    plan.add_argument("--mapping", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    importer = commands.add_parser("import-staging", help="幂等导入隔离账本，支持原产物恢复")
    importer.add_argument("--plan", type=Path, required=True)
    importer.add_argument("--staging", type=Path, required=True)
    importer.add_argument("--dry-run", action="store_true")
    formal = commands.add_parser("import-schema", help="全源归档并原子导入明确支持的正式 1.0 领域对象")
    formal.add_argument("--bundle", type=Path, required=True)
    formal.add_argument("--plan", type=Path, required=True)
    formal.add_argument("--target-env", default="ASTRA_1_0_MIGRATION_TARGET_URL")
    formal.add_argument("--ledger", type=Path, required=True)
    formal.add_argument("--artifact-root", type=Path, required=True)
    formal.add_argument("--output", type=Path, required=True)
    formal.add_argument("--dry-run", action="store_true")
    formal_report = commands.add_parser("reconcile-schema", help="只读核对正式 schema、来源账本与归档文件")
    formal_report.add_argument("--bundle", type=Path, required=True)
    formal_report.add_argument("--plan", type=Path, required=True)
    formal_report.add_argument("--target-env", default="ASTRA_1_0_MIGRATION_TARGET_URL")
    formal_report.add_argument("--ledger", type=Path, required=True)
    formal_report.add_argument("--artifact-root", type=Path, required=True)
    formal_report.add_argument("--output", type=Path, required=True)
    report = commands.add_parser("reconcile", help="逐类行数、源主键、关联和目标内容哈希对账")
    report.add_argument("--bundle", type=Path, required=True)
    report.add_argument("--plan", type=Path, required=True)
    report.add_argument("--staging", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    rollback = commands.add_parser("rollback-staging", help="仅删除该产物写入的 staging 行")
    rollback.add_argument("--plan-id", required=True)
    rollback.add_argument("--staging", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            source = os.environ.get(args.source_env)
            if not source:
                raise MigrationError("源连接环境变量未配置")
            result = export_bundle(
                source, args.output, read_json(args.freeze), args.source_commit, dry_run=args.dry_run
            )
            # 不打印来源地址、原始内容或冻结声明内的敏感部署信息。
            result = {
                "bundle_id": result["bundle_id"],
                "dry_run": args.dry_run,
                "table_counts": {name: table["count"] for name, table in result["tables"].items()},
            }
        elif args.command == "map":
            result = build_plan(args.bundle, read_json(args.mapping))
            if args.output.exists():
                raise MigrationError("映射产物已存在，禁止覆盖审计证据")
            write_json(args.output, result)
            result = {
                "plan_id": result["plan_id"],
                "records": len(result["records"]),
                "dangling_references": len(result["dangling_references"]),
                "cutover_allowed": False,
            }
        elif args.command == "import-staging":
            result = import_staging(read_json(args.plan), args.staging.resolve(), dry_run=args.dry_run)
        elif args.command == "import-schema":
            from .formal import import_schema

            target = os.environ.get(args.target_env)
            if not target:
                raise MigrationError("正式目标连接环境变量未配置")
            result = import_schema(
                args.bundle,
                read_json(args.plan),
                target,
                args.ledger.resolve(),
                args.artifact_root.resolve(),
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                write_json(args.output, result)
        elif args.command == "reconcile":
            result = reconcile(args.bundle, read_json(args.plan), args.staging.resolve())
            write_json(args.output, result)
            print(
                json.dumps(
                    {"passed_staging": result["passed_staging"], "cutover_allowed": False}, ensure_ascii=False
                )
            )
            return 0 if result["passed_staging"] else 2
        elif args.command == "reconcile-schema":
            from .formal import reconcile_schema

            target = os.environ.get(args.target_env)
            if not target:
                raise MigrationError("正式目标连接环境变量未配置")
            result = reconcile_schema(
                args.bundle,
                read_json(args.plan),
                target,
                args.ledger.resolve(),
                args.artifact_root.resolve(),
            )
            write_json(args.output, result)
            print(
                json.dumps(
                    {
                        "passed_formal_reconciliation": result["passed_formal_reconciliation"],
                        "cutover_allowed": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 0 if result["passed_formal_reconciliation"] else 2
        else:
            result = rollback_staging(args.staging.resolve(), args.plan_id)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except MigrationError as error:
        print(f"迁移停止：{error}", file=sys.stderr)
        return 2
    except Exception:
        # 驱动异常可包含 URL/SQL 参数，不能原样输出。
        print("迁移停止：未预期的离线工具错误；请在安全环境排查，不要公开原始连接异常", file=sys.stderr)
        return 2
