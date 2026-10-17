"""仓库地址、加密 PAT、进程内 git clone，以及 Worker 复制。

PAT 只在 askpass 子进程的环境里出现一次。URL、命令参数、日志和配置都不写明文。
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import get_settings
from app.domain import EmployeeStatus, EnvironmentStatus
from app.gateway.security import CredentialCipher
from app.models import CodeRepository, DigitalEmployee, GitCredential, OpenCodeExecutionEnvironment

Runner = Callable[[list[str], dict[str, str]], tuple[int, str, str]]

_ASKPASS = """#!/bin/sh
case "$1" in
  *Username*) printf '%s\\n' git ;;
  *) printf '%s\\n' "$ASTRA_GIT_TOKEN" ;;
esac
"""


class CloneError(RuntimeError):
    pass


class RepositoryBindingError(RuntimeError):
    pass


def cipher() -> CredentialCipher:
    return CredentialCipher(get_settings().gateway_master_key)


def assert_clean_url(url: str, token: str = "") -> None:
    if token and token in url:
        raise CloneError("仓库地址不能包含凭据")
    location = urlsplit(url)
    if location.username or location.password:
        raise CloneError("仓库地址不能包含凭据")


def redact_secret(text: str, secret: str) -> str:
    if secret:
        return text.replace(secret, "[已隐藏]")
    return text


def _default_runner(command: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stderr, completed.stdout


def clone_repository(
    url: str,
    branch: str,
    destination: str,
    token: str,
    *,
    runner: Runner | None = None,
) -> None:
    """真实的 git clone。不调用 git init，也不把 PAT 写进 URL。"""

    assert_clean_url(url, token)
    run = runner or _default_runner
    command = [
        "git",
        "-c",
        "credential.helper=",
        "clone",
        "--branch",
        branch,
        "--",
        url,
        destination,
    ]
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / "askpass"
        script.write_text(_ASKPASS, encoding="utf-8")
        script.chmod(stat.S_IRUSR | stat.S_IXUSR)
        env = os.environ.copy()
        env["GIT_ASKPASS"] = str(script)
        env["GIT_TERMINAL_PROMPT"] = "0"
        if token:
            env["ASTRA_GIT_TOKEN"] = token
        code, err, out = run(command, env)
    if code:
        message = redact_secret((err or out or "git clone 失败").strip(), token)
        raise CloneError(message or "git clone 失败")


def fresh_workspace(source: str, employee_id: str) -> str:
    if source.startswith("/"):
        parent = source.rsplit("/", 1)[0] or "/"
        return f"{parent}/{employee_id}"
    return f"./workspaces/{employee_id}"


def collect_skill_files(names: list[str], source: Path) -> list[dict[str, str]]:
    """从平台技能目录复制引用。不读取仓库里的 `.opencode/`。"""

    files: list[dict[str, str]] = []
    for name in names:
        path = source / name / "SKILL.md"
        if path.is_file():
            files.append({"name": name, "body": path.read_text(encoding="utf-8")})
    return files


async def create_repository(session: AsyncSession, *, url: str, branch: str, token: str) -> CodeRepository:
    assert_clean_url(url, token)
    repository = CodeRepository(id=uuid4().hex, url=url, branch=branch or "main")
    session.add(repository)
    await session.flush()
    session.add(GitCredential(repository_id=repository.id, token_ciphertext=cipher().encrypt(token)))
    await session.commit()
    await session.refresh(repository)
    return repository


async def bind_repository(
    session: AsyncSession,
    environment: OpenCodeExecutionEnvironment,
    repository_id: str,
) -> OpenCodeExecutionEnvironment:
    repository = await session.get(CodeRepository, repository_id)
    if repository is None:
        raise RepositoryBindingError("仓库不存在")
    current = environment.repository_id
    if current and current != repository.id:
        raise RepositoryBindingError("Worker 已绑定仓库")
    environment.repository_id = repository.id
    environment.branch = repository.branch
    await session.commit()
    await session.refresh(environment)
    return environment


async def copy_worker(
    session: AsyncSession,
    source: DigitalEmployee,
    *,
    new_id: str,
    name: str,
) -> DigitalEmployee:
    environment = source.execution_environment
    if environment is None:
        raise RepositoryBindingError("员工尚未配置 Agent 工作环境")
    if await session.get(DigitalEmployee, new_id):
        raise RepositoryBindingError("员工 ID 已存在")
    employee = DigitalEmployee(
        id=new_id,
        name=name,
        role=source.role,
        description=source.description,
        character_id=source.character_id,
        default_work_area=source.default_work_area,
        status=EmployeeStatus.IDLE,
        task_types=list(source.task_types or []),
        category_ids=list(source.category_ids or []),
        enabled=source.enabled,
        auto_claim=source.auto_claim,
        auto_execute=source.auto_execute,
        current_task_count=0,
    )
    session.add(employee)
    await session.flush()
    session.add(
        OpenCodeExecutionEnvironment(
            employee_id=employee.id,
            mode=environment.mode,
            name=environment.name,
            description=environment.description,
            host=environment.host,
            port=22,
            username=environment.username,
            ssh_password=None,
            opencode_server_port=14096,
            opencode_path=environment.opencode_path,
            model_name=environment.model_name,
            workspace_root=fresh_workspace(environment.workspace_root, employee.id),
            branch=environment.branch,
            repository_id=environment.repository_id,
            skill_refs=list(environment.skill_refs or []),
            mcp_refs=[dict(item) for item in environment.mcp_refs or [] if isinstance(item, dict)],
            labels=list(environment.labels or []),
            worker_channel=environment.worker_channel,
            status=EnvironmentStatus.UNKNOWN,
            status_detail={},
        )
    )
    await session.commit()
    return employee
