"""Stage 3 defaults stay off the names v0.9 already binds."""

import inspect
import os

from app.config.settings import Settings
from app.executors.opencode_local_server import SERVE_LOCK_DIR
from app.runtime.celery_app import celery
from app.runtime.remote_provisioning import AGENT_VENV, WORKER_SECRET_DIR
from app.worker_gateway.bus import RedisRouteBus


def test_process_defaults_do_not_collide_with_v09(monkeypatch):
    for key in list(os.environ):
        if key.startswith("ASTRA_"):
            monkeypatch.delenv(key, raising=False)
    settings = Settings(_env_file=None)

    registered = {name for name in celery.tasks if name.startswith(("nexus.", "astra."))}
    assert {"nexus.dispatch", "nexus.task-review", "nexus.task-wake"} <= registered
    assert not any(name.startswith("astra.") for name in registered)

    prefix = inspect.signature(RedisRouteBus.__init__).parameters["prefix"].default
    assert prefix == "nexus:worker-gateway"
    assert settings.redis_url.endswith("/1")
    assert settings.database_name == "nexus"
    assert settings.sqlalchemy_database_url.endswith("/nexus.db")
    assert SERVE_LOCK_DIR == "nexus-employee-serve"
    assert AGENT_VENV.startswith("/opt/nexus/")
    assert WORKER_SECRET_DIR == "/etc/nexus"
    assert settings.agentscope_base_url.endswith(":18000")
    assert settings.nexus_api_base.endswith(":18120")
    assert settings.task_mcp_port == 18202
    assert settings.mcp_port == 18201
    assert settings.assistant_opencode_port == 14097
    assert settings.remote_gateway_local_url.endswith(":18110")
    assert settings.opencode_server_port == 14096
    assert settings.database_username == "nexus"
    assert celery.conf.task_default_queue == "nexus-control"
    assert celery.conf.task_routes["nexus.dispatch"]["queue"] == "nexus-control"
