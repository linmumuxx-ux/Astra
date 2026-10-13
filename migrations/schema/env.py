import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from domains.database import Base

config = context.config
url = os.environ["ASTRA_V1_DATABASE_URL"]


def apply(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        await connection.run_sync(apply)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
