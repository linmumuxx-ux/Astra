"""Worker 租约与执行绑定。事务内只有短数据库操作，没有 Runtime/文件 I/O。"""

from __future__ import annotations

import hashlib

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from domains.core import DomainError, now
from domains.governance.service import audit, cas, get_required, serialize
from domains.identity.models import WorkspaceGrant
from domains.identity.service import authorize, current_principal
from domains.organization.models import Employee, Role, Team
from domains.runtime.models import AssetLock, Worker, WorkerLease
from domains.work.models import Task, TaskExecution

_ACTIVE_EXECUTIONS = {"BOUND", "RUNNING", "RECONCILE_REQUIRED"}


async def _authorize_task(session, principal, task, action):
    project_id = task.asset_scope.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        raise DomainError(409, "工程执行必须绑定明确的 project_id")
    await authorize(session, principal, action, task.team_id, project_id=project_id)
    employee = await get_required(session, Employee, task.owner_employee_id)
    if employee.team_id != task.team_id or employee.lifecycle != "ACTIVE":
        raise DomainError(409, "任务主责员工已停止履职或不在当前团队")
    return project_id, employee


async def _grant_snapshot(session, principal, employee, task, worker):
    """再次验证主责员工本人的权限，管理员点击派工不能替员工扩大岗位边界。"""
    project_id = task.asset_scope["project_id"]
    owner = await current_principal(session, employee.id)
    await authorize(session, owner, "task.dispatch", task.team_id, project_id=project_id)
    role = await get_required(session, Role, employee.role_id)
    team = await get_required(session, Team, task.team_id)
    grant = await session.scalar(
        select(WorkspaceGrant).where(
            WorkspaceGrant.actor_id == employee.id,
            WorkspaceGrant.team_id == task.team_id,
            WorkspaceGrant.project_id == project_id,
        )
    )
    return {
        "project_id": project_id,
        "initiator_id": principal.id,
        "owner_employee_id": employee.id,
        "employee_revision": employee.revision,
        "role_id": role.id,
        "role_revision": role.revision,
        "team_policy_revision": team.revision,
        "grant_id": grant.id,
        "grant_team_id": grant.team_id,
        "grant_revision": grant.revision,
        "grant_expires_at": grant.expires_at,
        "permissions": list(grant.permissions),
        "worker_revision": worker.revision,
        "runtime_version": worker.runtime_version,
        "runtime_base_url": worker.base_url,
        "workspace_roots": list(worker.workspace_roots),
        "asset_scope": dict(task.asset_scope),
    }


async def _reserve_shared_assets(session, task, *, expires_at):
    """私有 worktree 互不加锁；明确的外部共享写资产用稳定键独占。"""
    assets = task.asset_scope.get("shared_assets", [])
    if not isinstance(assets, list) or any(not isinstance(asset, str) or not asset for asset in assets):
        raise DomainError(400, "shared_assets 必须是明确的共享写资产标识列表")
    for asset in sorted(set(assets)):
        project_id = task.asset_scope["project_id"]
        key = hashlib.sha256(f"{project_id}\0{asset}".encode()).hexdigest()
        lock = await session.scalar(select(AssetLock).where(AssetLock.project_id == key))
        if lock is None:
            try:
                async with session.begin_nested():
                    lock = AssetLock(
                        project_id=key,
                        task_id=task.id,
                        scope=f"{project_id}:{asset}",
                        fence=1,
                        expires_at=expires_at,
                    )
                    session.add(lock)
                    await session.flush()
            except IntegrityError as exc:
                raise DomainError(409, "共享资产已被并发工作占用，请读取权威结果") from exc
        else:
            # 即便已过期，也必须先对账副作用，不能拿走旧 Task 的锁。
            if lock.task_id is not None:
                raise DomainError(409, "共享资产仍绑定其他执行，需先对账或等待释放")
            await cas(session, lock, {"task_id": task.id, "fence": lock.fence + 1, "expires_at": expires_at})


async def dispatch_task(
    session,
    principal,
    task_id: str,
    worker_id: str,
    *,
    lease_seconds: int = 120,
    health_freshness_seconds: int = 120,
    compatible_versions: tuple[str, ...] = ("1.18.35",),
):
    """只绑定执行与租约，不虚报 RUNNING；Runtime 启动在提交后单独处理。"""
    if not 10 <= lease_seconds <= 3600:
        raise DomainError(400, "Worker 租约须为 10–3600 秒")
    task = await get_required(session, Task, task_id)
    project_id, employee = await _authorize_task(session, principal, task, "task.dispatch")
    if task.read_only or task.status != "QUEUED":
        raise DomainError(409, "只有可写且排队中的业务任务可以派工")
    worker = await get_required(session, Worker, worker_id)
    if (
        not worker.enabled
        or worker.health != "HEALTHY"
        or worker.last_seen_at is None
        or worker.last_seen_at + health_freshness_seconds <= now()
    ):
        raise DomainError(409, "Worker 未通过最近的真实健康检查")
    if worker.runtime_version not in compatible_versions:
        raise DomainError(409, "Worker OpenCode 版本尚未通过当前部署兼容契约")
    if project_id not in worker.allowed_projects or not worker.workspace_roots:
        raise DomainError(403, "Worker 未被授权访问该工程或未配置工作区边界")
    if not set(task.required_capabilities).issubset(worker.capabilities):
        raise DomainError(409, "Worker 能力不能满足任务要求")
    active = await session.scalar(
        select(TaskExecution.id).where(
            TaskExecution.task_id == task.id,
            TaskExecution.superseded_by.is_(None),
            TaskExecution.state.in_(_ACTIVE_EXECUTIONS),
        )
    )
    if active:
        raise DomainError(409, "已有未结束执行，必须先对账，禁止重复派工")
    snapshot = await _grant_snapshot(session, principal, employee, task, worker)
    # CAS 将 Worker 配置、员工生命周期和 Task 主责/状态固定到短事务。
    await cas(session, worker, {})
    await cas(session, employee, {})
    await cas(session, task, {"status": "DISPATCHED"})
    free = await session.scalar(
        select(WorkerLease)
        .where(
            WorkerLease.worker_id == worker.id,
            WorkerLease.state == "FREE",
            WorkerLease.slot < worker.concurrent_slots,
        )
        .order_by(WorkerLease.slot)
    )
    if free is None:
        raise DomainError(409, "Worker 没有可用并发槽位；过期租约不能直接抢占")
    expires_at, fence = now() + lease_seconds, free.fence + 1
    changed = await session.execute(
        update(WorkerLease)
        .where(
            WorkerLease.id == free.id,
            WorkerLease.state == "FREE",
            WorkerLease.fence == free.fence,
            WorkerLease.revision == free.revision,
        )
        .values(
            state="ACTIVE", task_id=task.id, fence=fence, expires_at=expires_at, revision=free.revision + 1
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        raise DomainError(409, "Worker 槽位已被其他派工占用")
    await session.refresh(free)
    await _reserve_shared_assets(session, task, expires_at=expires_at)
    attempt = 1 + (
        await session.scalar(
            select(func.max(TaskExecution.attempt_no)).where(TaskExecution.task_id == task.id)
        )
        or 0
    )
    execution = TaskExecution(
        task_id=task.id,
        worker_id=worker.id,
        attempt_no=attempt,
        lease_id=free.id,
        lease_fence=fence,
        grant_snapshot=snapshot,
        state="BOUND",
    )
    session.add(execution)
    await session.flush()
    # 只在旧执行已结束并释放后建立下一尝试，旧轮次不能回写新轮次。
    await session.execute(
        update(TaskExecution)
        .where(
            TaskExecution.task_id == task.id,
            TaskExecution.id != execution.id,
            TaskExecution.superseded_by.is_(None),
        )
        .values(superseded_by=execution.id)
    )
    await audit(
        session,
        principal,
        task.team_id,
        "task.dispatched",
        execution,
        "执行已绑定 Worker 租约，等待原生 Runtime 启动",
    )
    return {"execution": serialize(execution), "lease": serialize(free)}


async def assert_current_execution(session, execution_id: str, *, expected_fence: int):
    """启动、结果写入和续租的共同 fencing；失效后只能进入人工/系统对账。"""
    execution = await get_required(session, TaskExecution, execution_id)
    lease = await get_required(session, WorkerLease, execution.lease_id)
    if (
        execution.superseded_by is not None
        or execution.state not in {"BOUND", "RUNNING"}
        or lease.state != "ACTIVE"
        or lease.task_id != execution.task_id
        or expected_fence != execution.lease_fence
        or lease.fence != expected_fence
        or lease.expires_at <= now()
    ):
        raise DomainError(409, "执行租约或轮次已失效，旧结果不可覆盖当前工作")
    return execution, lease


async def validate_execution_authority(session, execution_id: str, *, expected_fence: int):
    """外部 I/O 前重新核验权限；不能只信任派工时的快照。"""
    execution, lease = await assert_current_execution(session, execution_id, expected_fence=expected_fence)
    task = await get_required(session, Task, execution.task_id)
    worker = await get_required(session, Worker, execution.worker_id)
    owner = await current_principal(session, task.owner_employee_id)
    project_id, employee = await _authorize_task(session, owner, task, "task.dispatch")
    snapshot = execution.grant_snapshot
    role = await get_required(session, Role, employee.role_id)
    team = await get_required(session, Team, task.team_id)
    grant = await session.scalar(
        select(WorkspaceGrant).where(
            WorkspaceGrant.actor_id == employee.id,
            WorkspaceGrant.team_id == task.team_id,
            WorkspaceGrant.project_id == project_id,
        )
    )
    if (
        not worker.enabled
        or project_id not in worker.allowed_projects
        or worker.workspace_roots != snapshot.get("workspace_roots")
        or worker.runtime_version != snapshot.get("runtime_version")
        or worker.base_url != snapshot.get("runtime_base_url")
        or not set(task.required_capabilities).issubset(worker.capabilities)
        or grant.id != snapshot.get("grant_id")
        or grant.team_id != snapshot.get("grant_team_id")
        or grant.revision != snapshot.get("grant_revision")
        or role.id != snapshot.get("role_id")
        or role.revision != snapshot.get("role_revision")
        or team.revision != snapshot.get("team_policy_revision")
        or task.owner_employee_id != snapshot.get("owner_employee_id")
    ):
        raise DomainError(409, "授权、主责或政策已变更，必须停止新动作并重新确认")
    return execution, lease


async def renew_lease(session, execution_id: str, *, expected_fence: int, lease_seconds: int = 120):
    if not 10 <= lease_seconds <= 3600:
        raise DomainError(400, "Worker 租约须为 10–3600 秒")
    _, lease = await validate_execution_authority(session, execution_id, expected_fence=expected_fence)
    await cas(session, lease, {"expires_at": now() + lease_seconds})
    return lease


async def expire_worker_leases(session, principal):
    """可重跑的恢复扫描。过期只标待对账，不释放槽位、不重跑原 Task。"""
    leases = (
        await session.scalars(
            select(WorkerLease).where(WorkerLease.state == "ACTIVE", WorkerLease.expires_at <= now())
        )
    ).all()
    expired = []
    for lease in leases:
        task = await get_required(session, Task, lease.task_id)
        await authorize(
            session, principal, "runtime.recover", task.team_id, project_id=task.asset_scope.get("project_id")
        )
        changed = await session.execute(
            update(WorkerLease)
            .where(
                WorkerLease.id == lease.id,
                WorkerLease.state == "ACTIVE",
                WorkerLease.fence == lease.fence,
                WorkerLease.expires_at <= now(),
            )
            .values(state="RECONCILE_REQUIRED", revision=WorkerLease.revision + 1)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            continue
        await session.execute(
            update(TaskExecution)
            .where(
                TaskExecution.lease_id == lease.id,
                TaskExecution.lease_fence == lease.fence,
                TaskExecution.superseded_by.is_(None),
                TaskExecution.state.in_(["BOUND", "RUNNING"]),
            )
            .values(state="RECONCILE_REQUIRED", revision=TaskExecution.revision + 1)
        )
        await session.execute(
            update(Task)
            .where(Task.id == lease.task_id, Task.status.in_(["DISPATCHED", "RUNNING"]))
            .values(status="RECONCILE_REQUIRED", revision=Task.revision + 1)
        )
        expired.append(lease.id)
        await session.refresh(lease)
        await audit(
            session,
            principal,
            task.team_id,
            "execution.lease_expired",
            lease,
            "执行租约过期，保留绑定与槽位等待原生事实和副作用对账",
        )
    return expired


async def release_reconciled_execution(
    session,
    principal,
    execution_id: str,
    *,
    expected_fence: int,
    outcome: str,
    reconciliation_ref: str,
    evidence_refs: list[str] | None = None,
):
    """仅受权的人/系统在已核验原生 Session 和外部副作用后调用。

    SUBMITTED 只进入独立业务验收，不直接完成 Task。此函数本身不验证外部证据内容。
    """
    execution = await get_required(session, TaskExecution, execution_id)
    task = await get_required(session, Task, execution.task_id)
    project_id = task.asset_scope.get("project_id")
    await authorize(session, principal, "task.reconcile", task.team_id, project_id=project_id)
    if principal.kind not in {"HUMAN", "SYSTEM"}:
        raise DomainError(403, "员工/Worker 不得自行跳过独立对账和验收")
    if outcome not in {"SUBMITTED", "ABORTED", "FAILED"} or not reconciliation_ref:
        raise DomainError(400, "必须提供明确对账结论和可信核验引用")
    if outcome == "SUBMITTED" and (not execution.native_session_id or not evidence_refs):
        raise DomainError(409, "执行提交必须包含可核验原生 Session 与证据索引")
    lease = await get_required(session, WorkerLease, execution.lease_id)
    if (
        execution.superseded_by
        or execution.state not in _ACTIVE_EXECUTIONS
        or execution.lease_fence != expected_fence
        or lease.fence != expected_fence
        or lease.task_id != task.id
        or lease.state not in {"ACTIVE", "RECONCILE_REQUIRED"}
    ):
        raise DomainError(409, "对账针对的执行轮次已失效，不得释放新的租约")
    await cas(
        session,
        execution,
        {
            "state": outcome,
            "finished_at": now(),
            "evidence_refs": evidence_refs or [],
            "output_ref": reconciliation_ref,
        },
    )
    await cas(session, lease, {"state": "FREE", "task_id": None, "expires_at": 0})
    locks = (await session.scalars(select(AssetLock).where(AssetLock.task_id == task.id))).all()
    for lock in locks:
        await cas(session, lock, {"task_id": None, "expires_at": 0})
    await cas(session, task, {"status": "REVIEW" if outcome == "SUBMITTED" else "PAUSED"})
    await audit(
        session,
        principal,
        task.team_id,
        "execution.reconciled",
        execution,
        "对账结论已记录；任务仍需独立验收或人工处置",
    )
    return execution
