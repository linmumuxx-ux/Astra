import os
from contextlib import asynccontextmanager
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


@asynccontextmanager
async def isolated_database_url(tmp_path, filename):
    configured = os.environ.get("ASTRA_V1_TEST_MYSQL_SERVER")
    if not configured:
        yield f"sqlite+aiosqlite:///{tmp_path / filename}"
        return
    url = make_url(configured)
    if url.drivername != "mysql+asyncmy" or url.host != "127.0.0.1" or url.database:
        raise RuntimeError("MySQL 测试只接受显式本地隔离 Server，不能指定现有业务 schema")
    schema = "astra_v1_test_" + uuid4().hex
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    created = False
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4"))
            created = True
        yield url.set(database=schema).render_as_string(hide_password=False)
    finally:
        if created:
            async with engine.connect() as connection:
                await connection.execute(text(f"DROP DATABASE `{schema}`"))
        await engine.dispose()
