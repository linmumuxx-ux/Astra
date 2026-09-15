import asyncio

import pytest

from app.assistant.inspection import (
    _json_value,
    build_query,
    describe_resource,
    list_resources,
    resolve_fields,
    safe_columns,
)
from app.assistant.mcp_server import mcp


def test_inspector_exposes_core_resources_without_sensitive_columns():
    resources = {item["name"] for item in list_resources()["resources"]}

    assert {"tasks", "runs", "employees", "environments", "events", "dispatch"} <= resources
    assert "knowledge" not in resources
    environment_fields = set(safe_columns("environments"))
    assert "ssh_password" not in environment_fields
    assert "username" in environment_fields
    run_fields = set(safe_columns("runs"))
    assert "execution_token" not in run_fields
    assert "input_tokens" in run_fields
    assert "failure_code" in run_fields


def test_inspector_rejects_sensitive_or_unknown_fields():
    with pytest.raises(ValueError, match="不可读取"):
        resolve_fields("environments", ["ssh_password"])

    with pytest.raises(ValueError, match="不可读取"):
        build_query(
            "runs",
            fields=["id"],
            where=["execution_token=secret"],
        )

    with pytest.raises(ValueError, match="不支持的资源"):
        resolve_fields("raw_sql", ["id"])

    with pytest.raises(ValueError, match="不支持的资源"):
        resolve_fields("knowledge", ["id"])


def test_inspector_recursively_redacts_sensitive_json_keys():
    value = _json_value(
        {
            "status": "ERROR",
            "detail": {
                "access_token": "secret-token",
                "nested": [{"ssh_password": "secret-password", "reason": "timeout"}],
            },
        }
    )

    assert value["status"] == "ERROR"
    assert value["detail"]["access_token"] == "[REDACTED]"
    assert value["detail"]["nested"][0]["ssh_password"] == "[REDACTED]"
    assert value["detail"]["nested"][0]["reason"] == "timeout"


def test_inspector_describe_is_read_only_schema_view():
    description = describe_resource("events")
    fields = {item["name"] for item in description["fields"]}

    assert description["resource"] == "events"
    assert {"task_id", "run_id", "event_type", "message", "created_at"} <= fields


def test_assistant_mcp_exposes_generic_inspector_without_shell_or_sql_tools():
    tool_names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert "nexus_inspect" in tool_names
    assert not any("sql" in name.lower() for name in tool_names)
