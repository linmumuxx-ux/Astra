"""1.0 运维入口：显式迁移、管理员初始化、独立 API 启动。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from sqlalchemy import select

from domains.core import new_id
from domains.database import Database
from domains.identity.models import Actor
from domains.identity.service import issue_credential

ROOT = Path(__file__).resolve().parents[2]


async def bootstrap(url: str, name: str, token_file: Path):
    if token_file.exists():
        raise RuntimeError("凭据输出文件已存在，拒绝覆盖")
    db = Database(url)
    try:
        async with db.sessions() as session:
            if await session.scalar(select(Actor.id).where(Actor.kind == "HUMAN")):
                raise RuntimeError("已有人员身份；禁止重复 bootstrap，请使用受控人员管理")
            actor = Actor(id=new_id(), name=name, kind="HUMAN", permissions=["*"])
            session.add(actor)
            await session.flush()
            token = await issue_credential(session, actor)
            token_file.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w") as output:
                    output.write(token + "\n")
                await session.commit()
            except BaseException:
                token_file.unlink(missing_ok=True)
                raise
        print(f"管理员已初始化；短期凭据写入 {token_file}，请安全交付并及时轮换")
    finally:
        await db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Astra 1.0 运维入口")
    parser.add_argument("command", choices=["migrate", "bootstrap", "serve"])
    parser.add_argument("--name", default="管理员")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    url = os.environ.get("ASTRA_V1_DATABASE_URL")
    if not url:
        parser.error("必须显式配置 ASTRA_V1_DATABASE_URL，且指向独立 1.0 schema")
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(ROOT / "migrations/schema/alembic.ini")), "head")
    elif args.command == "bootstrap":
        if not args.token_file:
            parser.error("bootstrap 必须指定安全 --token-file（凭据不进入日志）")
        asyncio.run(bootstrap(url, args.name, args.token_file.resolve()))
    else:
        import uvicorn

        uvicorn.run("apps.api.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
