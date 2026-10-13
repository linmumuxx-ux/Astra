"""独立验收的原生证据读取协调；I/O 不在业务事务中执行。"""

from domains.core import DomainError
from domains.governance.service import get_required, serialize
from domains.runtime import NativeSessionBinding, RuntimePurpose
from domains.runtime.evidence import native_ref, native_tree, part_digest
from domains.runtime.execution_config import runtime_client
from domains.runtime.models import Worker
from domains.work.models import Task, TaskExecution
from domains.work.review import review_authority


async def review_snapshot(session, principal, execution_id, settings, *, for_review=True):
    execution = await get_required(session, TaskExecution, execution_id)
    task = await get_required(session, Task, execution.task_id)
    await review_authority(session, principal, task)
    if (
        task.read_only
        or execution.read_only
        or not execution.native_session_id
        or not execution.permission_digest
    ):
        raise DomainError(409, "此执行缺少可核验的新原生绑定，请查询历史归档证据")
    if for_review and (execution.superseded_by or execution.state != "SUBMITTED" or task.status != "REVIEW"):
        raise DomainError(409, "仅可验收当前已提交且可写的执行结果")
    config = settings.project(execution.worker_id, task.asset_scope["project_id"])
    if execution.grant_snapshot.get("execution_config_digest") != config.digest:
        raise DomainError(409, "验收的工程配置与执行绑定不一致")
    worker = await get_required(session, Worker, execution.worker_id)
    worker_data = serialize(worker)
    worker_data["credential_ref"] = worker.credential_ref
    return serialize(task), serialize(execution), worker_data, config


async def read_evidence(snapshot, *, client_factory=runtime_client):
    _, execution, worker, config = snapshot
    client = client_factory(worker, execution, config)
    binding = NativeSessionBinding(
        execution["native_session_id"],
        worker["id"],
        RuntimePurpose.TASK,
        execution["id"],
        execution["workspace_ref"],
        execution["permission_digest"],
    )
    return await native_tree(client, binding)


def evidence_payload(snapshot, messages):
    """即时呈现原生工具事实；不存消息副本，不把缺失退出码推断为成功。"""
    execution = snapshot[1]
    return {
        "execution_id": execution["id"],
        "items": [
            {
                "native_session_id": sid,
                "message_id": message["info"]["id"],
                "part_id": part["id"],
                "tool": part.get("tool"),
                "state": part.get("state", {}).get("status"),
                "input": part.get("state", {}).get("input"),
                "exit_code": part.get("state", {}).get("metadata", {}).get("exit"),
                "output": str(part.get("state", {}).get("output", ""))[:20000],
                "truncated": len(str(part.get("state", {}).get("output", ""))) > 20000,
                "matches_submission": native_ref(
                    sid, message["info"]["id"], part["id"], digest=part_digest(part)
                )
                in execution["evidence_refs"],
            }
            for sid, rows in messages.items()
            for message in rows
            for part in message.get("parts", [])
            if part.get("type") == "tool"
        ],
    }
