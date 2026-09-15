"""Shared read-only inspection primitives for assistant fallback diagnostics."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models import (
    DigitalEmployee,
    Event,
    Evidence,
    OpenCodeExecutionEnvironment,
    Run,
    RunDispatchOutbox,
    RunInquiry,
    SessionMessage,
    Task,
    TaskCategory,
    TaskSession,
    ToolUsage,
)

MAX_LIMIT = 50
MAX_TEXT_LENGTH = 8000

RESOURCE_MODELS = {
    "tasks": Task,
    "runs": Run,
    "employees": DigitalEmployee,
    "environments": OpenCodeExecutionEnvironment,
    "categories": TaskCategory,
    "events": Event,
    "evidence": Evidence,
    "sessions": TaskSession,
    "messages": SessionMessage,
    "inquiries": RunInquiry,
    "dispatch": RunDispatchOutbox,
    "tool_usage": ToolUsage,
}

SENSITIVE_COLUMN_NAMES = {
    "ssh_password",
    "password",
    "secret",
    "credential",
    "private_key",
    "api_key",
    "token",
    "access_token",
    "refresh_token",
    "execution_token",
}
SENSITIVE_SUFFIXES = (
    "_password",
    "_secret",
    "_credential",
    "_private_key",
    "_api_key",
    "_token",
    "_access_token",
    "_refresh_token",
)

DEFAULT_FIELDS = {
    "tasks": [
        "id",
        "task_type",
        "title",
        "status",
        "priority",
        "employee_id",
        "current_progress",
        "failure_reason",
        "human_required_reason",
        "last_activity_at",
        "created_at",
        "updated_at",
    ],
    "runs": [
        "id",
        "task_id",
        "employee_id",
        "run_number",
        "status",
        "executor_status",
        "failure_code",
        "failure_scope",
        "retryable",
        "recovery_action",
        "exit_code",
        "worker_id",
        "heartbeat_at",
        "started_at",
        "finished_at",
        "created_at",
    ],
    "employees": [
        "id",
        "name",
        "role",
        "status",
        "enabled",
        "current_task_count",
        "active_run_id",
        "last_heartbeat",
        "updated_at",
    ],
    "environments": [
        "employee_id",
        "mode",
        "name",
        "host",
        "port",
        "username",
        "opencode_server_port",
        "model_name",
        "workspace_root",
        "status",
        "status_detail",
        "last_checked_at",
    ],
    "events": [
        "id",
        "task_id",
        "employee_id",
        "run_id",
        "event_type",
        "phase",
        "message",
        "created_at",
    ],
}


def _is_sensitive_column(name: str) -> bool:
    lowered = name.lower()
    return lowered in SENSITIVE_COLUMN_NAMES or lowered.endswith(SENSITIVE_SUFFIXES)


def resource_model(resource: str):
    model = RESOURCE_MODELS.get(resource)
    if model is None:
        raise ValueError(f"不支持的资源：{resource}")
    return model


def safe_columns(resource: str) -> dict[str, Any]:
    model = resource_model(resource)
    return {
        column.name: column
        for column in model.__table__.columns
        if not _is_sensitive_column(column.name)
    }


def resolve_fields(resource: str, requested: list[str] | None = None) -> list[str]:
    columns = safe_columns(resource)
    if requested:
        fields = [item.strip() for item in requested if item.strip()]
    else:
        fields = [field for field in DEFAULT_FIELDS.get(resource, list(columns)[:12]) if field in columns]
    if not fields:
        raise ValueError("至少需要一个字段")
    unknown = [field for field in fields if field not in columns]
    if unknown:
        raise ValueError(f"字段不存在或不可读取：{', '.join(unknown)}")
    return list(dict.fromkeys(fields))


def _coerce_value(column, raw: str) -> Any:
    if raw.lower() == "null":
        return None
    try:
        python_type = column.type.python_type
    except (AttributeError, NotImplementedError):
        return raw
    if python_type is bool:
        lowered = raw.lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"字段 {column.name} 需要布尔值")
    if python_type is int:
        return int(raw)
    if python_type is float:
        return float(raw)
    if python_type is datetime:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return raw


def _split_filter(expression: str) -> tuple[str, str]:
    if "=" not in expression:
        raise ValueError(f"过滤条件必须是 field=value：{expression}")
    field, value = expression.split("=", 1)
    field = field.strip()
    if not field:
        raise ValueError(f"过滤字段不能为空：{expression}")
    return field, value


def _apply_where(query, model, resource: str, where: list[str] | None):
    columns = safe_columns(resource)
    for expression in where or []:
        field, raw = _split_filter(expression)
        column = columns.get(field)
        if column is None:
            raise ValueError(f"过滤字段不存在或不可读取：{field}")
        query = query.where(getattr(model, field) == _coerce_value(column, raw))
    return query


def build_query(
    resource: str,
    *,
    fields: list[str],
    where: list[str] | None = None,
    contains: list[str] | None = None,
    order_by: str | None = None,
    descending: bool = False,
    limit: int = 20,
) -> Select:
    model = resource_model(resource)
    columns = safe_columns(resource)
    query = select(*(getattr(model, field) for field in fields))
    query = _apply_where(query, model, resource, where)

    for expression in contains or []:
        field, raw = _split_filter(expression)
        column = columns.get(field)
        if column is None:
            raise ValueError(f"搜索字段不存在或不可读取：{field}")
        if not isinstance(column.type, (String, Text)):
            raise ValueError(f"contains 仅支持文本字段：{field}")
        query = query.where(getattr(model, field).contains(raw))

    if order_by:
        if order_by not in columns:
            raise ValueError(f"排序字段不存在或不可读取：{order_by}")
        order_column = getattr(model, order_by)
        query = query.order_by(order_column.desc() if descending else order_column.asc())
    return query.limit(max(1, min(limit, MAX_LIMIT)))


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _is_sensitive_column(str(key)) else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _json_value(value: Any) -> Any:
    value = _sanitize_value(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and len(value) > MAX_TEXT_LENGTH:
        return value[:MAX_TEXT_LENGTH] + "...[truncated]"
    if isinstance(value, (dict, list)):
        encoded = json.dumps(value, ensure_ascii=False, default=str)
        if len(encoded) > MAX_TEXT_LENGTH:
            return encoded[:MAX_TEXT_LENGTH] + "...[truncated]"
    return value


def list_resources() -> dict[str, Any]:
    return {
        "resources": [
            {
                "name": resource,
                "table": model.__tablename__,
                "default_fields": resolve_fields(resource),
            }
            for resource, model in RESOURCE_MODELS.items()
        ]
    }


def describe_resource(resource: str) -> dict[str, Any]:
    columns = safe_columns(resource)
    return {
        "resource": resource,
        "fields": [
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
            }
            for column in columns.values()
        ],
    }


async def query_resource(
    session: AsyncSession,
    *,
    resource: str,
    fields: list[str] | None = None,
    where: list[str] | None = None,
    contains: list[str] | None = None,
    order_by: str | None = None,
    descending: bool = False,
    limit: int = 20,
) -> dict[str, Any]:
    resolved_fields = resolve_fields(resource, fields)
    query = build_query(
        resource,
        fields=resolved_fields,
        where=where,
        contains=contains,
        order_by=order_by,
        descending=descending,
        limit=limit,
    )
    rows = (await session.execute(query)).all()
    items = [
        {field: _json_value(value) for field, value in zip(resolved_fields, row, strict=True)}
        for row in rows
    ]
    return {"resource": resource, "fields": resolved_fields, "items": items, "returned": len(items)}


async def count_resource(
    session: AsyncSession,
    *,
    resource: str,
    where: list[str] | None = None,
) -> dict[str, Any]:
    model = resource_model(resource)
    query = _apply_where(select(func.count()).select_from(model), model, resource, where)
    count = await session.scalar(query)
    return {"resource": resource, "count": int(count or 0)}
