from datetime import UTC, datetime

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import EmployeeStatus, EnvironmentStatus
from app.models import DigitalEmployee, OpenCodeExecutionEnvironment, TaskCategory

DEFAULT_CATEGORIES = (
    ("testing-platform", "测试平台", "测试平台相关问题与需求", 10),
    ("automation-engineering", "自动化工程", "自动化工程建设与维护", 20),
    ("quality-defense", "防线运营", "质量防线运行与治理", 30),
)


async def bootstrap_categories(session: AsyncSession) -> None:
    changed = False
    for category_id, name, description, sort_order in DEFAULT_CATEGORIES:
        if await session.get(TaskCategory, category_id):
            continue
        session.add(
            TaskCategory(
                id=category_id,
                name=name,
                description=description,
                enabled=True,
                sort_order=sort_order,
            )
        )
        changed = True
    if changed:
        await session.commit()


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
            task_types=item.get("task_types", ["ISSUE", "REQUIREMENT"]),
            category_ids=item.get(
                "category_ids",
                ["testing-platform", "automation-engineering", "quality-defense"],
            ),
            enabled=item.get("enabled", True),
            auto_claim=item.get("policy", {}).get("auto_claim", True),
            auto_execute=item.get("policy", {}).get("auto_execute", True),
            max_auto_retries=item.get("policy", {}).get("max_auto_retries", 3),
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
                name=environment.get("name", "本地 Agent 工作环境"),
                description=environment.get("description", ""),
                host=environment.get("host"),
                port=environment.get("port", 22),
                username=environment.get("username"),
                auth_method=environment.get("auth_method", "SSH_AGENT"),
                ssh_key_path=environment.get("ssh_key_path"),
                opencode_path=environment.get("opencode_path", "opencode"),
                model_name=environment.get("model_name"),
                workspace_root=environment.get("workspace_root", "./workspaces"),
                labels=environment.get("labels", []),
                status=EnvironmentStatus.UNKNOWN,
            )
        )
        changed = True
    if changed:
        await session.commit()
