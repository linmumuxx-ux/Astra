from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import get_settings

settings = get_settings()
database_url = settings.sqlalchemy_database_url
if database_url.startswith("sqlite"):
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)

engine_options: dict = {"pool_pre_ping": True}
if database_url.startswith("mysql"):
    engine_options["pool_recycle"] = settings.database_pool_recycle

engine = create_async_engine(database_url, **engine_options)


if database_url.startswith("mysql"):

    @event.listens_for(engine.sync_engine, "connect")
    def configure_mysql_connection(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute(f"SET NAMES {settings.database_charset}")
        finally:
            cursor.close()


SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_database() -> None:
    from app.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
