from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import EmployeeStatus, TaskStatus
from app.models import DigitalEmployee, Event, Run, Task


async def seed_demo_data(session: AsyncSession) -> None:
    if await session.scalar(select(func.count(DigitalEmployee.id))):
        return
    now = datetime.now(UTC)
    employee = DigitalEmployee(
        id="astra-01",
        name="Astra-01",
        role="测试执行员工",
        description="长期在线，负责测试脚本生成、执行、修复与结果验证。",
        status=EmployeeStatus.WORKING,
        capabilities=[
            "script_generate",
            "script_review",
            "script_execute",
            "script_repair",
            "result_verify",
        ],
        source_scope=["nr_test_system", "manual"],
        max_concurrency=1,
        current_task_count=1,
        online_since=now - timedelta(hours=8, minutes=26),
        last_heartbeat=now,
    )
    session.add(employee)

    tasks = [
        Task(
            id="T-20260827-001",
            source="nr_test_system",
            external_task_id="NRTS-5821",
            task_type="script_generate",
            title="登录流程自动化脚本开发",
            description="补充登录主流程与异常密码场景，完成真实环境执行。",
            input={
                "case_id": "TC-LOGIN-018",
                "verification": {
                    "test_command": ["pytest", "tests/test_login.py", "-q"],
                    "required_files": ["tests/test_login.py"],
                },
            },
            definition_of_done=["脚本生成完成", "代码检视通过", "真实执行 PASS", "证据已保存"],
            priority="P1",
            priority_weight=3,
            status=TaskStatus.RUNNING,
            employee_id="astra-01",
            workspace="/workspaces/T-20260827-001",
            opencode_session_id="ses_astra_01_5821",
            current_phase="repairing",
            progress=68,
            retry_count=1,
            max_retry_count=3,
            claimed_at=now - timedelta(minutes=34),
            started_at=now - timedelta(minutes=32),
            created_at=now - timedelta(minutes=38),
        ),
        Task(
            id="T-20260827-002",
            source="nr_test_system",
            external_task_id="NRTS-5824",
            task_type="script_execute",
            title="订单支付流程回归验证",
            description="支付回调环境不可用，等待人工确认测试窗口。",
            input={"case_id": "TC-PAY-042"},
            definition_of_done=["订单支付回归通过"],
            priority="P0",
            priority_weight=4,
            status=TaskStatus.WAIT_HUMAN,
            employee_id=None,
            current_phase="environment_blocked",
            progress=46,
            human_required_reason="测试环境支付回调服务连续 3 次返回 503，需要确认环境恢复时间。",
            retry_count=3,
            max_retry_count=3,
            created_at=now - timedelta(hours=2, minutes=18),
        ),
        Task(
            id="T-20260827-003",
            source="manual",
            external_task_id=None,
            task_type="script_review",
            title="用户权限边界用例代码检视",
            description="检查团队角色与全局角色叠加场景。",
            input={"review_target": "tests/test_team_permissions.py"},
            definition_of_done=["检视项全部关闭", "回归测试通过"],
            priority="P2",
            priority_weight=2,
            status=TaskStatus.COMPLETED,
            employee_id="astra-01",
            workspace="/workspaces/T-20260827-003",
            opencode_session_id="ses_astra_01_review",
            current_phase="completed",
            progress=100,
            result={"passed": True, "summary": "12 项检查通过，pytest 28 passed"},
            claimed_at=now - timedelta(hours=4, minutes=10),
            started_at=now - timedelta(hours=4, minutes=8),
            finished_at=now - timedelta(hours=3, minutes=31),
            created_at=now - timedelta(hours=4, minutes=15),
        ),
        Task(
            id="T-20260826-014",
            source="nr_test_system",
            external_task_id="NRTS-5797",
            task_type="script_generate",
            title="产品版本升级场景脚本生成",
            description="覆盖版本规则的补集语义与边界值。",
            input={"case_id": "TC-VERSION-011"},
            definition_of_done=["脚本生成", "测试通过"],
            priority="P2",
            priority_weight=2,
            status=TaskStatus.COMPLETED,
            employee_id="astra-01",
            current_phase="completed",
            progress=100,
            result={"passed": True, "summary": "pytest 19 passed"},
            finished_at=now - timedelta(hours=6, minutes=12),
            created_at=now - timedelta(hours=7),
        ),
        Task(
            id="T-20260826-011",
            source="nr_test_system",
            external_task_id="NRTS-5768",
            task_type="script_execute",
            title="基础设施健康检查回归",
            description="验证 MySQL、Redis 与 Celery 基础链路。",
            input={},
            definition_of_done=["健康检查通过"],
            priority="P3",
            priority_weight=1,
            status=TaskStatus.FAILED,
            employee_id="astra-01",
            current_phase="failed",
            progress=78,
            failure_reason="Redis 测试实例不可达",
            finished_at=now - timedelta(days=1, hours=1),
            created_at=now - timedelta(days=1, hours=2),
        ),
    ]
    session.add_all(tasks)
    await session.flush()

    run = Run(
        id="RUN-DEMO-001",
        task_id="T-20260827-001",
        employee_id="astra-01",
        run_number=1,
        status="FAILED",
        executor_type="opencode_cli",
        opencode_session_id="ses_astra_01_5821",
        started_at=now - timedelta(minutes=31),
        finished_at=now - timedelta(minutes=12),
        exit_code=1,
        result={"summary": "登录断言定位器失效，已进入自动修复"},
    )
    session.add(run)
    await session.flush()
    timeline = [
        ("TASK_CREATED", "created", "从 nr_test_system 导入任务", -38),
        ("TASK_CLAIMED", "claimed", "Astra-01 已领取任务", -34),
        ("WORKSPACE_CREATED", "workspace", "独立 Workspace 已创建", -33),
        ("OPENCODE_STARTED", "executing", "OpenCode Session 已启动", -31),
        ("SCRIPT_GENERATED", "script_generate", "登录流程脚本生成完成", -22),
        ("CODE_REVIEWED", "code_review", "静态检视通过", -18),
        ("EXECUTION_FAILED", "executing", "首次执行失败：登录按钮定位器失效", -12),
        ("FAULT_ANALYZED", "fault_analysis", "已定位为前端 data-testid 变更", -9),
        ("REPAIR_COMPLETED", "repairing", "正在应用最小脚本修复", -3),
    ]
    session.add_all(
        [
            Event(
                task_id="T-20260827-001",
                employee_id="astra-01",
                run_id="RUN-DEMO-001" if event_type not in {"TASK_CREATED", "TASK_CLAIMED"} else None,
                event_type=event_type,
                phase=phase,
                message=message,
                detail={},
                created_at=now + timedelta(minutes=offset),
            )
            for event_type, phase, message, offset in timeline
        ]
    )
    session.add(
        Event(
            task_id="T-20260827-002",
            event_type="WAIT_HUMAN",
            phase="environment_blocked",
            message="支付回调环境不可用，已请求人工介入",
            detail={"http_status": 503},
            created_at=now - timedelta(minutes=47),
        )
    )
    await session.commit()
