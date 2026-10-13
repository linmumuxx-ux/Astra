"""任务独立验收规则；原生证据校验由应用层在事务外完成。"""

from domains.core import DomainError, now
from domains.governance.service import audit, cas, get_required
from domains.identity.service import authorize, revalidate_principal
from domains.organization.models import Employee
from domains.runtime.evidence import verify_citation
from domains.work.models import Task, TaskExecution, TaskReview
from domains.work.service import task_event


async def review_authority(session, principal, task):
    principal = await revalidate_principal(session, principal)
    await authorize(
        session, principal, "task.review", task.team_id, project_id=task.asset_scope.get("project_id")
    )
    if principal.kind not in {"HUMAN", "EMPLOYEE"}:
        raise DomainError(403, "Worker 与执行系统身份不能自行完成业务验收")
    employee = await get_required(session, Employee, task.owner_employee_id)
    if principal.id not in {employee.id, employee.manager_id}:
        raise DomainError(403, "只有业务主责员工或其授权负责人可以验收")
    return principal


def validate_review(data, task, execution, messages):
    if data.expected_task_revision != task["revision"]:
        raise DomainError(409, "任务版本已变化，请重新读取验收标准")
    indexes = [item.criterion_index for item in data.criteria_results]
    if sorted(indexes) != list(range(len(task["acceptance_criteria"]))):
        raise DomainError(400, "必须逐条覆盖原始验收标准，不得重复、遗漏或替换标准")
    if data.outcome == "COMPLETED" and any(
        not item.passed or not item.evidence for item in data.criteria_results
    ):
        raise DomainError(409, "每条标准均需独立通过结论及真实证据，不可凭 Worker 自述完成")
    if data.outcome == "REWORK" and all(item.passed for item in data.criteria_results):
        raise DomainError(400, "返工必须说明至少一项未通过标准")
    refs = []
    for item in data.criteria_results:
        if item.passed and not item.evidence:
            raise DomainError(409, "通过的验收标准必须有可核验证据")
        for citation in item.evidence:
            ref = verify_citation(messages, citation, execution["native_session_id"])
            if ref not in execution["evidence_refs"]:
                raise DomainError(409, "引用未出现在当前执行提交的证据索引中")
            refs.append(ref)
    return sorted(set(refs))


async def apply_review(session, principal, task_id, data, snapshot, refs):
    task = await get_required(session, Task, task_id)
    principal = await review_authority(session, principal, task)
    execution = await get_required(session, TaskExecution, data.execution_id)
    if (
        task.revision != data.expected_task_revision
        or task.status != "REVIEW"
        or execution.task_id != task.id
        or execution.state != "SUBMITTED"
        or execution.superseded_by
        or execution.revision != snapshot[1]["revision"]
    ):
        raise DomainError(409, "验收期间责任或执行已变化，旧结论不可关闭当前工作")
    review = TaskReview(
        task_id=task.id,
        execution_id=execution.id,
        reviewer_id=principal.id,
        outcome=data.outcome,
        criteria_results=[item.model_dump() for item in data.criteria_results],
        evidence_refs=refs,
    )
    session.add(review)
    await session.flush()
    status = {"COMPLETED": "COMPLETED", "REWORK": "QUEUED", "WAIT_HUMAN": "WAIT_HUMAN"}[data.outcome]
    await cas(
        session,
        task,
        {
            "status": status,
            "completed_at": now() if status == "COMPLETED" else None,
            "latest_result": {
                "review_id": review.id,
                "outcome": data.outcome,
                "execution_id": execution.id,
                "evidence_refs": refs,
            },
        },
    )
    # 验收事件版本独立于 Worker 提交，固定到不可变 Review 引用。
    await cas(session, execution, {})
    await task_event(session, principal, task, execution, data.outcome.lower())
    await audit(session, principal, task.team_id, "task.reviewed", review, "原始标准的独立验收结论已记录")
    return review
