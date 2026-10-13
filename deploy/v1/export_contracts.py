"""从真实新模型、路由与 MCP 注册表导出契约快照，不连接业务库。"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/astra-1.0"


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


async def export():
    sys.path.insert(0, str(ROOT))
    from agents.tools import build_tools
    from apps.api.main import create_app
    from apps.api.schemas import PersonaDecision
    from domains.database import Base, Database

    OUT.mkdir(parents=True, exist_ok=True)
    application = create_app("sqlite+aiosqlite:///:memory:")
    write_json("openapi.json", application.openapi())
    write_json("persona-decision.schema.json", PersonaDecision.model_json_schema())
    database = Database("sqlite+aiosqlite:///:memory:")
    server = build_tools(
        database, api_url="https://astra.example.invalid", resource_url="https://astra.example.invalid/mcp"
    )
    write_json(
        "tools.json",
        [tool.model_dump(by_alias=True, exclude_none=True) for tool in await server.list_tools()],
    )
    lines = [
        "# Astra 1.0 当前 schema 数据字典",
        "",
        "此快照由 `deploy/v1/export_contracts.py` 从新 ORM 生成；模型与静态 Alembic 迁移为实施事实源。",
        "当前 30 张领域表，初始 revision `1000`；时间字段为 Unix 秒，原生 Session ID 为索引而非消息副本。",
        "所有 Record 含稳定 UUID、revision 和 created_at；只有明确的一次性迁移可写只读历史记录。",
        "",
    ]
    for name, table in sorted(Base.metadata.tables.items()):
        lines += [f"## {name}", "", "| 列 | 类型 | 可空 | 约束/关联 |", "| --- | --- | --- | --- |"]
        for column in table.columns:
            constraints = []
            if column.primary_key:
                constraints.append("主键")
            if column.unique:
                constraints.append("唯一")
            constraints.extend(f"FK {fk.target_fullname}" for fk in column.foreign_keys)
            lines.append(
                f"| {column.name} | {column.type} | {'是' if column.nullable else '否'} | "
                f"{', '.join(constraints) or '—'} |"
            )
        unique = [
            ", ".join(col.name for col in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        if unique:
            lines += ["", "组合唯一约束：" + "；".join(unique) + "。"]
        lines += [""]
    (OUT / "data-dictionary.md").write_text("\n".join(lines))
    await application.state.db.engine.dispose()
    await database.engine.dispose()


if __name__ == "__main__":
    asyncio.run(export())
