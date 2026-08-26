from datetime import UTC, datetime

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import EmployeeStatus, EnvironmentStatus
from app.models import DigitalEmployee, OpenCodeExecutionEnvironment


async def bootstrap_employees(session: AsyncSession, config_path) -> None:
    path = config_path / "employees.yaml"
    if not path.is_file():
        return
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    changed = False
    for item in payload.get("employees", []):
        if not item.get("enabled", True):
            continue
        employee = await session.get(DigitalEmployee, item["id"])
        if employee:
            continue
        now = datetime.now(UTC)
        employee = DigitalEmployee(
            id=item["id"],
            name=item.get("name", item["id"]),
            role=item.get("role", "数字员工"),
            description=item.get("description", ""),
            status=EmployeeStatus.IDLE,
            capabilities=item.get("capabilities", []),
            skills=item.get("skills", []),
            source_scope=item.get("sources", []),
            enabled=item.get("enabled", True),
            auto_claim=item.get("policy", {}).get("auto_claim", True),
            auto_execute=item.get("policy", {}).get("auto_execute", True),
            auto_repair=item.get("policy", {}).get("auto_repair", True),
            max_auto_retries=item.get("policy", {}).get("max_auto_retries", 3),
            max_concurrency=item.get("max_concurrency", 1),
            online_since=now,
            last_heartbeat=now,
        )
        session.add(employee)
        await session.flush()
        environment = item.get("execution_environment", {})
        session.add(
            OpenCodeExecutionEnvironment(
                employee_id=employee.id,
                mode=environment.get("mode", "LOCAL"),
                name=environment.get("name", "本地 OpenCode"),
                description=environment.get("description", ""),
                host=environment.get("host"),
                port=environment.get("port", 22),
                username=environment.get("username"),
                auth_method=environment.get("auth_method", "SSH_AGENT"),
                ssh_key_path=environment.get("ssh_key_path"),
                opencode_path=environment.get("opencode_path", "opencode"),
                workspace_root=environment.get("workspace_root", "./workspaces"),
                labels=environment.get("labels", []),
                status=EnvironmentStatus.UNKNOWN,
            )
        )
        changed = True
    if changed:
        await session.commit()
