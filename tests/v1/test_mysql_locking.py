import os

import httpx
import pytest
from sqlalchemy import update

from domains.identity.models import Actor

from . import test_domains
from .test_domains import post

api = test_domains.api
pytestmark = pytest.mark.skipif(not os.getenv("ASTRA_V1_TEST_MYSQL_SERVER"), reason="需独立真实 MySQL 实例")


async def test_real_mysql_lock_timeout_rolls_back_and_retries_same_operation_key(api):
    app, client, admin_id = api
    async with app.state.db.sessions.begin() as locker:
        await locker.execute(update(Actor).where(Actor.id == admin_id).values(revision=Actor.revision))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers=client.headers,
        ) as contender:
            failed = await post(contender, "teams", {"name": "锁冲突后重试"}, key="mysql-lock-retry")
            assert failed.status_code == 409, failed.text
            assert "SQL" not in failed.text and "UPDATE" not in failed.text
    retried = await post(client, "teams", {"name": "锁冲突后重试"}, key="mysql-lock-retry")
    assert retried.status_code == 200, retried.text
    assert len((await client.get("/api/v1/teams")).json()) == 1
