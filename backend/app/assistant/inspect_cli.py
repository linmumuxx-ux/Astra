"""CLI wrapper for the platform assistant read-only database inspector."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.assistant.inspection import (
    RESOURCE_MODELS,
    count_resource,
    describe_resource,
    list_resources,
    query_resource,
)
from app.database import SessionLocal


def _print(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-assistant-inspect",
        description="Astra 平台助手只读数据库检查工具；不支持任意 SQL 或写操作。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("resources", help="列出允许检查的资源")

    describe = subparsers.add_parser("describe", help="查看资源可读取字段")
    describe.add_argument("resource", choices=sorted(RESOURCE_MODELS))

    query = subparsers.add_parser("query", help="查询只读资源")
    query.add_argument("resource", choices=sorted(RESOURCE_MODELS))
    query.add_argument("--fields", help="逗号分隔的返回字段")
    query.add_argument("--where", action="append", default=[], metavar="FIELD=VALUE")
    query.add_argument("--contains", action="append", default=[], metavar="FIELD=TEXT")
    query.add_argument("--order-by")
    query.add_argument("--desc", action="store_true")
    query.add_argument("--limit", type=int, default=20)

    count = subparsers.add_parser("count", help="按等值条件统计")
    count.add_argument("resource", choices=sorted(RESOURCE_MODELS))
    count.add_argument("--where", action="append", default=[], metavar="FIELD=VALUE")
    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.command == "resources":
        _print(list_resources())
        return 0
    if args.command == "describe":
        _print(describe_resource(args.resource))
        return 0

    async with SessionLocal() as session:
        if args.command == "query":
            fields = [item.strip() for item in args.fields.split(",")] if args.fields else None
            result = await query_resource(
                session,
                resource=args.resource,
                fields=fields,
                where=args.where,
                contains=args.contains,
                order_by=args.order_by,
                descending=args.desc,
                limit=args.limit,
            )
        else:
            result = await count_resource(session, resource=args.resource, where=args.where)
    _print(result)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(async_main(args))
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
