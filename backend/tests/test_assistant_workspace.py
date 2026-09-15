from pathlib import Path

from app.assistant.server import ASSISTANT_WORKSPACE, AssistantOpenCodeServerManager
from app.config.settings import PROJECT_ROOT, Settings


def test_assistant_workspace_is_repository_owned(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ASTRA_ASSISTANT_WORKSPACE_DIR", str(tmp_path / "external-assistant"))

    settings = Settings()
    manager = AssistantOpenCodeServerManager(settings, binary="opencode")

    assert not hasattr(settings, "assistant_workspace_dir")
    assert manager.workspace == ASSISTANT_WORKSPACE
    assert manager.workspace == PROJECT_ROOT / "nexus-assistant"
    assert manager.workspace != tmp_path / "external-assistant"


def test_assistant_workspace_contains_runtime_contract():
    manager = AssistantOpenCodeServerManager(Settings(), binary="opencode")

    assert manager.workspace_errors() == []
    assert (manager.workspace / "opencode.json").is_file()
    assert (manager.workspace / "AGENTS.md").is_file()
    assert (manager.workspace / ".opencode/agents/platform-assistant.md").is_file()
