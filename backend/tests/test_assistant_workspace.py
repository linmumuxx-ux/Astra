import json
from pathlib import Path

from app.assistant.server import ASSISTANT_WORKSPACE, AssistantOpenCodeServerManager
from app.config.settings import PROJECT_ROOT, Settings


EXPECTED_SKILLS = {
    "nexus-task-ops",
    "nexus-run-triage",
    "nexus-knowledge-qa",
}


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


def test_assistant_workspace_has_only_method_skills():
    skills_root = ASSISTANT_WORKSPACE / ".opencode/skills"
    skills = {
        path.parent.name
        for path in skills_root.glob("*/SKILL.md")
    }

    assert skills == EXPECTED_SKILLS
    for skill in EXPECTED_SKILLS:
        text = (skills_root / skill / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert f"name: {skill}\n" in text
        assert "description:" in text
        assert "## 自迭代" in text


def test_assistant_workspace_configures_platform_and_library_mcp():
    config = json.loads((ASSISTANT_WORKSPACE / "opencode.json").read_text(encoding="utf-8"))

    assert config["mcp"]["nexus-assistant"]["command"] == ["astra-assistant-mcp"]
    assert config["mcp"]["nexus-library"]["command"] == ["astra-library-mcp"]
    assert config["mcp"]["nexus-library"]["environment"]["ASTRA_MCP_TRANSPORT"] == "stdio"
    assert config["permission"]["skill"]["*"] == "deny"
    assert config["permission"]["skill"]["nexus-*"] == "allow"
