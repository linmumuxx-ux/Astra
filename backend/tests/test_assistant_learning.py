import asyncio

import pytest

from app.assistant.mcp_server import build_skill_experience_payload, mcp


def _evidence():
    return [
        {
            "evidence_type": "user_correction",
            "content": "用户明确纠正了原处理方式，并给出可复用的正确边界。",
            "result": "corrected",
        }
    ]


def test_skill_experience_payload_uses_repository_skill_and_server_owned_metadata():
    payload = build_skill_experience_payload(
        skill_name="NEXUS-TASK-OPS",
        title="线上故障应创建问题任务",
        summary="用户纠正了任务类型判断。",
        content_md="# 适用场景\n线上故障修复。",
        evidence=_evidence(),
        tags=["task-type"],
        experience_data={"skill": "nexus-forged", "scenario": "online-incident"},
    )

    assert payload.title.startswith("[nexus-task-ops] ")
    assert payload.tags[:2] == ["assistant-skill", "nexus-task-ops"]
    assert payload.experience_data["skill"] == "nexus-task-ops"
    assert payload.experience_data["scenario"] == "online-incident"
    assert len(payload.evidence) == 1


@pytest.mark.parametrize(
    "skill_name",
    ["nexus-not-exists", "other-skill", "nexus-../task-ops", ""],
)
def test_skill_experience_payload_rejects_unknown_or_invalid_skill(skill_name: str):
    with pytest.raises(ValueError):
        build_skill_experience_payload(
            skill_name=skill_name,
            title="无效经验",
            summary="不应写入",
            content_md="# 内容",
            evidence=_evidence(),
        )


def test_skill_experience_payload_requires_real_title_and_evidence():
    with pytest.raises(ValueError, match="标题"):
        build_skill_experience_payload(
            skill_name="nexus-run-triage",
            title="   ",
            summary="缺少标题",
            content_md="# 内容",
            evidence=_evidence(),
        )

    with pytest.raises(ValueError, match="证据"):
        build_skill_experience_payload(
            skill_name="nexus-run-triage",
            title="诊断路径",
            summary="没有证据不能沉淀",
            content_md="# 内容",
            evidence=[],
        )


def test_assistant_mcp_exposes_learning_tool_without_duplicate_library_tools():
    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "nexus_experience_submit" in tool_names
    assert not any(name.startswith("library_") for name in tool_names)
