from pathlib import PurePath

import pytest

from app.domain import TaskType
from app.executors.opencode_prompt import (
    bind_task_prompt_context,
    build_task_prompt,
    resolve_task_prompt_context,
)
from app.models import Task, TaskCategory
from app.runtime.run_coordinator import RunCoordinator


def make_task(task_type: TaskType) -> Task:
    return Task(
        id=f"TASK-{task_type.value}",
        source="manual",
        task_type=task_type,
        category_id="CAT-001",
        title="验证分类提示词",
        description="确认 Runtime 会使用任务分类配置的提示词。",
        acceptance_criteria=[{"id": "AC-01", "content": "分类提示词进入实际执行 Prompt"}],
    )


def make_category() -> TaskCategory:
    return TaskCategory(
        id="CAT-001",
        name="自动化工程",
        task_prompt="REQUIREMENT_CATEGORY_PROMPT_MARKER",
        question_prompt="ISSUE_CATEGORY_PROMPT_MARKER",
        enabled=True,
    )


def test_issue_runtime_prompt_uses_question_prompt_only():
    task = make_task(TaskType.ISSUE)
    context = resolve_task_prompt_context(task, make_category())
    bind_task_prompt_context(task, context)

    prompt = build_task_prompt(task, PurePath("/workspace"))

    assert context is not None
    assert context.prompt_kind == "question_prompt"
    assert "任务类型：\n问题" in prompt
    assert "任务分类：\n自动化工程" in prompt
    assert "ISSUE_CATEGORY_PROMPT_MARKER" in prompt
    assert "REQUIREMENT_CATEGORY_PROMPT_MARKER" not in prompt
    assert "ASTRA_RESULT_JSON:" in prompt


def test_requirement_runtime_prompt_uses_task_prompt_only():
    task = make_task(TaskType.REQUIREMENT)
    context = resolve_task_prompt_context(task, make_category())
    bind_task_prompt_context(task, context)

    prompt = build_task_prompt(task, PurePath("/workspace"), native_question=True)

    assert context is not None
    assert context.prompt_kind == "task_prompt"
    assert "任务类型：\n需求" in prompt
    assert "REQUIREMENT_CATEGORY_PROMPT_MARKER" in prompt
    assert "ISSUE_CATEGORY_PROMPT_MARKER" not in prompt
    assert "OpenCode 原生 question Tool" in prompt
    assert "ASTRA_RESULT_JSON:" in prompt


def test_blank_category_prompt_degrades_to_generic_runtime_prompt():
    task = make_task(TaskType.ISSUE)
    category = make_category()
    category.question_prompt = "  \n  "
    context = resolve_task_prompt_context(task, category)
    bind_task_prompt_context(task, context)

    prompt = build_task_prompt(task, PurePath("/workspace"))

    assert context is not None
    assert context.prompt is None
    assert "任务分类：\n自动化工程" in prompt
    assert "分类执行要求：" not in prompt
    assert "ASTRA_RESULT_JSON:" in prompt


@pytest.mark.asyncio
async def test_run_coordinator_resolves_category_prompt_from_category_id():
    task = make_task(TaskType.ISSUE)
    category = make_category()
    requested = []

    class FakeSession:
        async def get(self, model, key):
            requested.append((model, key))
            return category

    context = await RunCoordinator._resolve_prompt_context(FakeSession(), task)

    assert requested == [(TaskCategory, "CAT-001")]
    assert context is not None
    assert context.category_id == "CAT-001"
    assert context.category_name == "自动化工程"
    assert context.prompt == "ISSUE_CATEGORY_PROMPT_MARKER"
