"""独立 1.0 数据库。应用启动不隐式迁移或播种。"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from domains.core import Base
from domains.governance import models as governance  # noqa: F401
from domains.identity import models as identity  # noqa: F401
from domains.knowledge import models as knowledge  # noqa: F401
from domains.messaging import models as messaging  # noqa: F401
from domains.organization import models as organization  # noqa: F401
from domains.personas import models as personas  # noqa: F401
from domains.runtime import models as runtime  # noqa: F401
from domains.work import models as work  # noqa: F401


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine.sync_engine, "connect")
            def configure(dbapi, _record):
                cursor = dbapi.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()

    async def create_for_tests(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
