import json
from pathlib import Path

from app.assistant.server import ASSISTANT_WORKSPACE, AssistantOpenCodeServerManager
from app.config.settings import PROJECT_ROOT, Settings


EXPECTED_SKILLS = {
    "nexus-task-ops",
    "nexus-run-triage",
    "nexus-knowledge-qa",
}

READ_ONLY_PERMISSIONS = ("read", "glob", "grep", "list", "lsp")
DENIED_PERMISSIONS = (
    "edit",
    "write",
    "bash",
    "task",
    "webfetch",
    "websearch",
    "external_directory",
)


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
    skills = {path.parent.name for path in skills_root.glob("*/SKILL.md")}

    assert skills == EXPECTED_SKILLS
    for skill in EXPECTED_SKILLS:
        text = (skills_root / skill / "SKILL.md").read_text(encoding="utf-8")
        assert text.startswith("---\n")
        assert f"name: {skill}\n" in text
        assert "description:" in text
        assert "## 自迭代" in text
        assert "nexus_experience_submit" in text


def test_assistant_workspace_keeps_read_only_fallback_but_blocks_mutation():
    config = json.loads((ASSISTANT_WORKSPACE / "opencode.json").read_text(encoding="utf-8"))

    assert set(config["mcp"]) == {"nexus-assistant"}
    assert config["mcp"]["nexus-assistant"]["command"] == ["astra-assistant-mcp"]
    assert config["permission"]["skill"]["*"] == "deny"
    assert config["permission"]["skill"]["nexus-*"] == "allow"
    for permission in READ_ONLY_PERMISSIONS:
        assert config["permission"][permission] == "allow"
    for permission in DENIED_PERMISSIONS:
        assert config["permission"][permission] == "deny"

    agent = (ASSISTANT_WORKSPACE / ".opencode/agents/platform-assistant.md").read_text(encoding="utf-8")
    for permission in READ_ONLY_PERMISSIONS:
        assert f"  {permission}: allow\n" in agent
    for permission in DENIED_PERMISSIONS:
        assert f"  {permission}: deny\n" in agent
    assert "nexus_inspect" in agent
    assert "nexus_experience_submit" in agent
    assert "library_submit_experience" not in agent

    mcp_server = (PROJECT_ROOT / "backend/app/assistant/mcp_server.py").read_text(encoding="utf-8")
    assert '@server.tool(name="nexus_inspect"' in mcp_server
    assert '@server.tool(name="nexus_experience_submit"' in mcp_server


def test_assistant_skill_routing_evals_cover_direct_skill_inspection_and_learning_paths():
    evals = json.loads(
        (ASSISTANT_WORKSPACE / "evals/skill-routing.json").read_text(encoding="utf-8")
    )

    assert len(evals) >= 10
    assert {item["expected_skill"] for item in evals if item["expected_skill"]} == EXPECTED_SKILLS
    assert any(item["expected_skill"] is None for item in evals)
    assert any("nexus_inspect" in item["expected_tools"] for item in evals)
    assert any(item["learning_signal"] for item in evals)
    assert any("nexus_experience_submit" in item["expected_tools"] for item in evals)
