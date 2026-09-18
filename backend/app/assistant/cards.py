"""业务卡片统一协议。

卡片由后端根据真实业务对象确定性生成，模型不得直接控制任意 URL。
actions 只允许两类：``navigate``（平台内置路由）和 ``assistant_operation``
（把请求交回助手走 prepare → confirm 流程）。
"""

from __future__ import annotations

from typing import Any

from app.models import DigitalEmployee, KnowledgeItem, Run, Task
from app.runtime.presentation import TASK_STATUS

TASK_STATUS_LABEL = {key: value["label"] for key, value in TASK_STATUS.items()}

EMPLOYEE_STATUS_LABEL = {
    "OFFLINE": "离线",
    "IDLE": "空闲",
    "WORKING": "工作中",
    "WAIT_HUMAN": "待人工",
    "PAUSED": "已暂停",
    "ERROR": "异常",
}

RUN_STATUS_LABEL = {
    "QUEUED": "排队中",
    "STARTING": "启动中",
    "RUNNING": "执行中",
    "WAITING_INPUT": "等待输入",
    "COMPLETED": "已完成",
    "FAILED": "已失败",
    "SUSPENDED": "已挂起",
    "TIMEOUT": "已超时",
    "LOST": "运行丢失",
    "CANCELLED": "已取消",
}

OPERATION_LABEL = {
    "task_create": "创建任务",
    "task_cancel": "取消任务",
    "task_retry": "重试任务",
    "task_resume": "恢复任务",
    "task_reassign": "重新分配任务",
}


def _navigate(label: str, target: str) -> dict[str, str]:
    return {"type": "navigate", "label": label, "target": target}


def _operation(label: str, operation: str) -> dict[str, str]:
    return {"type": "assistant_operation", "label": label, "operation": operation}


def task_card(task: Task) -> dict[str, Any]:
    employee = task.employee
    fields = [
        {"label": "状态", "value": TASK_STATUS_LABEL.get(task.status, task.status)},
        {"label": "类型", "value": task.task_type},
        {"label": "优先级", "value": task.priority},
        {"label": "执行员工", "value": employee.name if employee else (task.employee_id or "未分配")},
        {"label": "当前进展", "value": task.current_progress or "-"},
    ]
    if task.failure_reason:
        fields.append({"label": "失败原因", "value": task.failure_reason})
    actions = [_navigate("查看任务", f"/tasks/{task.id}")]
    if task.status in {"PENDING", "RUNNING", "WAITING"}:
        actions.append(_operation("停止任务", "task_cancel"))
    if task.status == "FAILED":
        actions.append(_operation("继续处理", "task_retry"))
    if task.status == "PENDING" and not task.current_session_id:
        actions.append(_operation("重新分配", "task_reassign"))
    return {
        "card_type": "task",
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "status_label": TASK_STATUS_LABEL.get(task.status, task.status),
        "fields": fields,
        "actions": actions,
    }


def employee_card(employee: DigitalEmployee) -> dict[str, Any]:
    fields = [
        {"label": "状态", "value": EMPLOYEE_STATUS_LABEL.get(employee.status, employee.status)},
        {"label": "岗位", "value": employee.role},
        {"label": "当前任务数", "value": str(employee.current_task_count)},
        {"label": "支持类型", "value": "、".join(employee.task_types) or "-"},
    ]
    return {
        "card_type": "employee",
        "id": employee.id,
        "title": employee.name,
        "status": employee.status,
        "status_label": EMPLOYEE_STATUS_LABEL.get(employee.status, employee.status),
        "fields": fields,
        "actions": [_navigate("查看员工", f"/employees/{employee.id}")],
    }


def run_card(run: Run) -> dict[str, Any]:
    fields = [
        {"label": "状态", "value": RUN_STATUS_LABEL.get(run.status, run.status)},
        {"label": "第几次执行", "value": f"#{run.run_number}"},
        {"label": "模型", "value": run.model_name or "-"},
        {"label": "Token", "value": str(run.total_tokens or "-")},
    ]
    if run.exit_code is not None:
        fields.append({"label": "退出码", "value": str(run.exit_code)})
    if run.failure_code:
        fields.append({"label": "失败类型", "value": run.failure_code})
    if run.worker_id:
        fields.append({"label": "Worker", "value": run.worker_id})
    return {
        "card_type": "run",
        "id": run.id,
        "title": f"{run.task_id} 的第 {run.run_number} 次执行",
        "status": run.status,
        "status_label": RUN_STATUS_LABEL.get(run.status, run.status),
        "fields": fields,
        "actions": [_navigate("查看运行", f"/tasks/{run.task_id}")],
    }


def knowledge_card(item: KnowledgeItem) -> dict[str, Any]:
    fields = [
        {"label": "类型", "value": item.type},
        {"label": "状态", "value": item.status},
    ]
    if item.tags:
        fields.append({"label": "标签", "value": "、".join(item.tags[:6])})
    if item.summary:
        fields.append({"label": "摘要", "value": item.summary[:160]})
    return {
        "card_type": "knowledge",
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "status_label": "已发布" if item.status == "published" else item.status,
        "fields": fields,
        "actions": [_navigate("查看知识", "/library")],
    }


def confirm_card(
    operation_id: str, operation_type: str, risk_level: str, preview: dict[str, Any]
) -> dict[str, Any]:
    return {
        "card_type": "confirm",
        "operation_id": operation_id,
        "operation_type": operation_type,
        "operation_label": OPERATION_LABEL.get(operation_type, operation_type),
        "risk_level": risk_level,
        "status": "WAITING_CONFIRM",
        "preview": preview,
    }


CARD_PART_TYPE = {
    "task": "TASK_CARD",
    "employee": "EMPLOYEE_CARD",
    "run": "RUN_CARD",
    "knowledge": "KNOWLEDGE_CARD",
}
