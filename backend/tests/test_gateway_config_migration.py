"""0032 删除版本历史，同时保留已保存配置和永久吊销记录。"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, select

from app.gateway.models import (
    GatewayAuditEvent,
    GatewayHealthCheck,
    GatewayKey,
    GatewayNode,
    GatewayPool,
    GatewayRequest,
    GatewayRoute,
    utcnow,
)
from app.gateway.security import gateway_key_digest

BACKEND = Path(__file__).resolve().parents[1]
RETAINED_MODELS = (
    GatewayPool,
    GatewayNode,
    GatewayRoute,
    GatewayKey,
    GatewayHealthCheck,
    GatewayRequest,
    GatewayAuditEvent,
)


def upgrade(database_path, revision):
    environment = {
        **os.environ,
        "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{database_path.as_posix()}",
        "ASTRA_ENVIRONMENT": "development",
        "ASTRA_SEED_DEMO": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def retained_rows(connection):
    return {
        model.__tablename__: [
            dict(row)
            for row in connection.execute(
                select(Table(model.__tablename__, MetaData(), autoload_with=connection))
            ).mappings()
        ]
        for model in RETAINED_MODELS
    }


def test_0032_drops_history_without_applying_old_snapshot_or_changing_saved_data(tmp_path):
    database_path = tmp_path / "gateway-upgrade.db"
    upgrade(database_path, "0031_api_gateway_control")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(GatewayPool.__table__.insert().values(id="gp_keep", name="保留资源池"))
            connection.execute(
                GatewayNode.__table__.insert().values(
                    id="gn_keep",
                    name="保留节点",
                    pool_id="gp_keep",
                    base_url="https://saved.example.com",
                    models=["saved-model"],
                )
            )
            connection.execute(
                GatewayRoute.__table__.insert().values(id="gr_keep", model="saved-model", pool_id="gp_keep")
            )
            connection.execute(
                GatewayKey.__table__.insert().values(
                    id="gk_revoked",
                    name="永久吊销 Key",
                    key_prefix="agw_revoked",
                    key_digest=gateway_key_digest("agw_revoked"),
                    enabled=False,
                    revoked_at=utcnow(),
                )
            )
            connection.execute(
                GatewayHealthCheck.__table__.insert().values(
                    node_id="gn_keep",
                    probe_type="NETWORK",
                    success=True,
                )
            )
            connection.execute(
                GatewayRequest.__table__.insert().values(
                    id="req_keep",
                    key_id="gk_revoked",
                    node_id="gn_keep",
                    status_code=200,
                    total_tokens=9,
                )
            )
            connection.execute(
                GatewayAuditEvent.__table__.insert().values(
                    actor="astra",
                    actor_role="system",
                    action="key.revoke",
                    resource_type="key",
                    resource_id="gk_revoked",
                )
            )
            history = Table("gateway_config_versions", MetaData(), autoload_with=connection)
            connection.execute(
                history.insert().values(
                    version=1,
                    status="CURRENT",
                    note="过期的发布配置",
                    published_by="legacy-admin",
                    published_at=utcnow(),
                    created_at=utcnow(),
                    snapshot={
                        "nodes": [{"id": "gn_keep", "base_url": "https://obsolete.example.com"}],
                        "keys": [{"id": "gk_revoked", "enabled": True, "revoked_at": None}],
                    },
                )
            )
            before = retained_rows(connection)
    finally:
        engine.dispose()

    upgrade(database_path, "0032_gateway_saved_config")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            assert "gateway_config_versions" not in inspect(connection).get_table_names()
            assert retained_rows(connection) == before
            assert connection.scalar(select(GatewayNode.base_url)) == "https://saved.example.com"
            key = connection.execute(select(GatewayKey.enabled, GatewayKey.revoked_at)).one()
            assert key.enabled is False
            assert key.revoked_at is not None
    finally:
        engine.dispose()


def test_0034_adds_deletion_marker_without_changing_existing_keys(tmp_path):
    database_path = tmp_path / "key-deletion-upgrade.db"
    upgrade(database_path, "0033_employee_character")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            keys = Table("gateway_keys", MetaData(), autoload_with=connection)
            connection.execute(keys.insert().values(
                id="gk_keep", name="已有 Key", key_prefix="agw_keep", key_digest="keep-digest",
                allowed_models=[], max_concurrency=0, enabled=True,
                created_at=utcnow(), updated_at=utcnow(),
            ))
            before = dict(connection.execute(select(keys)).mappings().one())
    finally:
        engine.dispose()

    upgrade(database_path, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            keys = Table("gateway_keys", MetaData(), autoload_with=connection)
            upgraded = dict(connection.execute(select(keys)).mappings().one())
            assert upgraded.pop("deleted_at") is None
            assert upgraded == before
            connection.execute(keys.update().values(enabled=False, revoked_at=utcnow(), deleted_at=utcnow()))
            deleted = dict(connection.execute(select(keys)).mappings().one())
    finally:
        engine.dispose()

    environment = {
        **os.environ, "ASTRA_DATABASE_URL": f"sqlite+aiosqlite:///{database_path.as_posix()}",
        "ASTRA_ENVIRONMENT": "development", "ASTRA_SEED_DEMO": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0033_employee_character"],
        cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            keys = Table("gateway_keys", MetaData(), autoload_with=connection)
            assert "deleted_at" not in keys.c
            deleted.pop("deleted_at")
            assert dict(connection.execute(select(keys)).mappings().one()) == deleted
    finally:
        engine.dispose()
