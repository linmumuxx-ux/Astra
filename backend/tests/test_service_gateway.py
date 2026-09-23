"""统一服务脚本的 Gateway 集成校验。

不启动真实进程：只校验 ``scripts/astra_service.py`` 组装出的命令、就绪等待和
正式模式校验，确保 API 中转数据面以独立进程运行且不自动发布草稿。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SCRIPT = ROOT / "scripts" / "astra_service.py"


def _load_service_module():
    spec = importlib.util.spec_from_file_location("astra_service_under_test", SERVICE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


service = _load_service_module()
GATEWAY_MODULE = "app.gateway.server:app"


def _settings(*, gateway_enabled: bool = True, **overrides):
    base = {
        "gateway_enabled": gateway_enabled,
        "gateway_master_key": None,
        "gateway_control_credentials": "",
        "redis_url": "redis://127.0.0.1:6379/0",
        "mcp_transport": "stdio",
        "resolved_runtime_dir": Path("/tmp/astra-run"),
        "resolved_log_dir": Path("/tmp/astra-logs"),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _local_command(executable, args):
    return [executable, *args]


def test_gateway_runs_as_standalone_data_plane():
    command = service.gateway_command("pro")
    assert command[command.index("-m") + 1] == "uvicorn"
    assert GATEWAY_MODULE in command
    assert str(service.GATEWAY_PORT) in command
    # 长连接数据面必须独立于主 Backend。
    assert GATEWAY_MODULE not in service.backend_command("pro")


def test_core_services_adds_gateway_only_when_enabled():
    enabled = service.core_services("pro", _settings(gateway_enabled=True), "npm", _local_command)
    disabled = service.core_services(
        "pro", _settings(gateway_enabled=False), "npm", _local_command
    )
    assert "gateway" in [name for name, *_ in enabled]
    assert "gateway" not in [name for name, *_ in disabled]
    gateway_entry = next(entry for entry in enabled if entry[0] == "gateway")
    assert GATEWAY_MODULE in gateway_entry[1]
    # Frontend 保持最后启动，Gateway 先于它。
    assert enabled[-1][0] == "frontend"


def test_start_core_waits_for_gateway_health(monkeypatch):
    processes: dict[str, dict[str, object]] = {}
    ready_urls: list[str] = []

    def fake_spawn(settings, name, command, cwd, *, env=None):
        processes[name] = {"pid": 1, "log": f"/tmp/{name}.log", "command": command, "cwd": str(cwd)}
        return processes[name]

    monkeypatch.setattr(service, "spawn", fake_spawn)
    monkeypatch.setattr(service, "wait_process", lambda name, info: None)
    monkeypatch.setattr(service, "wait_worker", lambda name, info: None)
    monkeypatch.setattr(service, "wait_http", lambda name, url, timeout=45: ready_urls.append(url))

    service.start_core("dev", _settings(gateway_enabled=True), "npm", _local_command, processes)

    assert "gateway" in processes
    assert f"http://127.0.0.1:{service.GATEWAY_PORT}/healthz" in ready_urls


def test_gateway_startup_never_publishes_draft():
    source = (ROOT / "backend" / "app" / "gateway" / "server.py").read_text(encoding="utf-8")
    assert "publish" not in source.lower()


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateway_master_key": None, "gateway_control_credentials": "admin-token"},
        {"gateway_master_key": "fernet-key", "gateway_control_credentials": ""},
        {"gateway_master_key": "fernet-key", "gateway_control_credentials": "admin-token", "redis_url": ""},
    ],
)
def test_production_gateway_validation_rejects_missing_dependencies(overrides):
    with pytest.raises(RuntimeError):
        service.validate_gateway_production(_settings(gateway_enabled=True, **overrides))


def test_production_gateway_validation_accepts_complete_config():
    service.validate_gateway_production(
        _settings(
            gateway_enabled=True,
            gateway_master_key="fernet-key",
            gateway_control_credentials="admin-token",
        )
    )


def test_production_gateway_validation_skips_when_disabled():
    service.validate_gateway_production(
        _settings(gateway_enabled=False, gateway_master_key=None, gateway_control_credentials="")
    )