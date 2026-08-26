from datetime import UTC, datetime

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import EmployeeStatus
from app.models import DigitalEmployee


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
        session.add(
            DigitalEmployee(
                id=item["id"],
                name=item.get("name", item["id"]),
                role=item.get("role", "数字员工"),
                description=item.get("description", ""),
                status=EmployeeStatus.IDLE,
                capabilities=item.get("capabilities", []),
                source_scope=item.get("sources", []),
                max_concurrency=item.get("max_concurrency", 1),
                online_since=now,
                last_heartbeat=now,
            )
        )
        changed = True
    if changed:
        await session.commit()
