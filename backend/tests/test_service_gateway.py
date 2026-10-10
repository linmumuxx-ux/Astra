"""统一服务脚本的 Gateway 集成校验。

不启动真实进程：只校验 ``scripts/astra_service.py`` 组装出的命令、就绪等待和
正式模式校验，确保 API 中转数据面以独立进程运行并直接加载保存配置。
"""

from __future__ import annotations

import importlib.util
import json
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


def test_gateway_startup_has_no_publication_workflow():
    source = (ROOT / "backend" / "app" / "gateway" / "server.py").read_text(encoding="utf-8")
    assert "publish" not in source.lower()


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateway_master_key": None},
        {"gateway_master_key": "fernet-key", "redis_url": ""},
    ],
)
def test_production_gateway_validation_rejects_missing_dependencies(overrides):
    with pytest.raises(RuntimeError):
        service.validate_gateway_production(_settings(gateway_enabled=True, **overrides))


def test_production_gateway_validation_accepts_config_without_management_credentials():
    service.validate_gateway_production(
        _settings(
            gateway_enabled=True,
            gateway_master_key="fernet-key",
        )
    )


def test_production_gateway_validation_skips_when_disabled():
    service.validate_gateway_production(
        _settings(gateway_enabled=False, gateway_master_key=None)
    )


def _workspace_ui_tree(
    tmp_path: Path,
    *,
    installed: list[str],
    upstream_tag: str | None = "v1.18.31",
    upstream_raw: str | None = None,
):
    frontend = tmp_path / "frontend"
    (frontend / "node_modules").mkdir(parents=True)
    bundles = frontend / "public" / "opencode-workspace"
    bundles.mkdir(parents=True)
    # 历史遗留的根产物存在，但版本化产物才是 Runtime 实际引用的入口。
    (bundles / "index.html").write_text("legacy", encoding="utf-8")
    for version in installed:
        (bundles / version).mkdir(parents=True)
        (bundles / version / "index.html").write_text("ok", encoding="utf-8")
    upstream = tmp_path / "workspace-ui"
    upstream.mkdir()
    # upstream_tag=None 表示 UPSTREAM.json 缺失，upstream_raw 用于写入损坏内容。
    if upstream_raw is not None:
        (upstream / "UPSTREAM.json").write_text(upstream_raw, encoding="utf-8")
    elif upstream_tag is not None:
        (upstream / "UPSTREAM.json").write_text(
            json.dumps({"tag": upstream_tag}), encoding="utf-8"
        )
    (tmp_path / ".env").write_text("", encoding="utf-8")
    return frontend


def test_validate_start_accepts_default_and_upstream_bundles(tmp_path, monkeypatch):
    frontend = _workspace_ui_tree(
        tmp_path, upstream_tag="v1.18.31", installed=["1.2.27", "1.18.31"]
    )
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "FRONTEND", frontend)

    service.validate_start("dev", _settings(opencode_workspace_ui_default_version="1.2.27"))


def test_validate_start_rejects_missing_upstream_bundle(tmp_path, monkeypatch):
    # 根 index.html 与默认版本都存在，只有上游版本包缺失。
    frontend = _workspace_ui_tree(tmp_path, upstream_tag="v1.18.31", installed=["1.2.27"])
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "FRONTEND", frontend)

    with pytest.raises(RuntimeError) as excinfo:
        service.validate_start("dev", _settings(opencode_workspace_ui_default_version="1.2.27"))

    message = str(excinfo.value)
    assert "1.18.31" in message
    assert "index.html" in message


def test_validate_start_rejects_missing_default_bundle(tmp_path, monkeypatch):
    # 上游版本包存在，只有默认版本（历史 RuntimeSession 回退）包缺失。
    frontend = _workspace_ui_tree(tmp_path, upstream_tag="v1.18.31", installed=["1.18.31"])
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "FRONTEND", frontend)

    with pytest.raises(RuntimeError) as excinfo:
        service.validate_start("dev", _settings(opencode_workspace_ui_default_version="1.2.27"))

    message = str(excinfo.value)
    assert "1.2.27" in message
    assert "index.html" in message
    # 默认版本产物是仓库内提交的静态资源；提示必须给出恢复方式，
    # 不能只建议仅构建上游版本的 workspace_ui build。
    assert "restore" in message.lower()


@pytest.mark.parametrize("upstream_raw", [None, "{ not valid json"])
def test_validate_start_rejects_invalid_upstream_metadata(
    tmp_path, monkeypatch, upstream_raw
):
    # 上游元数据缺失或损坏时必须显式失败，不能静默跳过固定上游 UI 校验。
    if upstream_raw is None:
        frontend = _workspace_ui_tree(tmp_path, upstream_tag=None, installed=["1.2.27"])
    else:
        frontend = _workspace_ui_tree(tmp_path, upstream_raw=upstream_raw, installed=["1.2.27"])
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "FRONTEND", frontend)

    with pytest.raises(RuntimeError) as excinfo:
        service.validate_start("dev", _settings(opencode_workspace_ui_default_version="1.2.27"))

    assert "UPSTREAM.json" in str(excinfo.value)