"""个人 Git Memory。数据库 head 是唯一可见版本；Git 只存不可变内容。

Git I/O 必须在事务外执行。先构造提交，再在短事务中 CAS head；失败的提交
不会成为员工上下文。权限、岗位、目标与 Task 状态从不从这些文件加载。
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from domains.core import DomainError, now
from domains.governance.service import audit, cas, get_required
from domains.identity.service import authorize, team_visible
from domains.messaging.models import Message
from domains.messaging.service import channel_access
from domains.organization.models import Employee
from domains.personas.models import EmployeeState, SourceEvent
from domains.work.models import Task

HEAD = re.compile(r"[a-f0-9]{40}\Z")
NOTE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\.md\Z")


async def memory_access(session, principal, employee_id, *, write=False):
    employee = await get_required(session, Employee, employee_id)
    if not await team_visible(session, principal, employee.team_id) or principal.id not in {
        employee.id,
        employee.manager_id,
    }:
        raise DomainError(403, "个人记忆仅本人及负责人可见，不随任务交接转让")
    if write:
        await authorize(session, principal, "memory.write", employee.team_id)
        if employee.lifecycle != "ACTIVE":
            raise DomainError(409, "暂停或归档员工的记忆不能继续写入")
    state = await session.scalar(select(EmployeeState).where(EmployeeState.employee_id == employee_id))
    if not state:
        raise DomainError(409, "员工长期工作状态缺失")
    return employee, state


async def verify_sources(session, principal, employee, source_refs):
    """私人来源同时验证写入者与记忆所属员工，避免负责人把他人 DM 注入上下文。"""
    from domains.identity.service import current_principal

    owner = await current_principal(session, employee.id)
    for ref in source_refs:
        kind, separator, object_id = ref.partition("/")
        if not separator:
            raise DomainError(400, "记忆来源必须引用明确业务对象")
        if kind == "messages":
            obj = await get_required(session, Message, object_id)
            await channel_access(session, principal, obj.channel_id)
            channel = await channel_access(session, owner, obj.channel_id)
            team_id = channel.team_id
        elif kind == "source-events":
            obj = await get_required(session, SourceEvent, object_id)
            team_id = obj.team_id
            if obj.source == "channel":
                await channel_access(session, principal, obj.payload_ref["channel_id"])
                await channel_access(session, owner, obj.payload_ref["channel_id"])
        elif kind == "tasks":
            obj = await get_required(session, Task, object_id)
            team_id = obj.team_id
        else:
            raise DomainError(400, "记忆来源仅接受 Task、Message 或 SourceEvent")
        if team_id != employee.team_id:
            raise DomainError(403, "记忆来源不在员工团队内")


async def publish_memory(session, principal, employee_id, data, prepared_head):
    employee, state = await memory_access(session, principal, employee_id, write=True)
    await verify_sources(session, principal, employee, data.source_refs)
    if state.memory_head != data.expected_head:
        raise DomainError(409, "记忆版本已变化，请读取当前版本后重新编辑")
    await cas(session, state, {"memory_head": prepared_head})
    await audit(session, principal, employee.team_id, "memory.updated", state, "个人记忆版本已更新")
    return {"employee_id": employee_id, "memory_head": prepared_head, "revision": state.revision}


class GitMemory:
    def __init__(self, root: str):
        path = Path(root)
        if not path.is_absolute() or ".." in path.parts:
            raise DomainError(503, "个人记忆根目录必须配置为绝对路径")
        self.root = path

    @classmethod
    def configured(cls):
        root = os.getenv("ASTRA_V1_MEMORY_ROOT")
        if not root:
            raise DomainError(503, "个人记忆存储尚未配置")
        return cls(root)

    @staticmethod
    def _head(value):
        if value is not None and not HEAD.fullmatch(value):
            raise DomainError(400, "无效的 Git Memory 版本")

    @staticmethod
    def _safe(path):
        for parent in [path, *path.parents]:
            if parent.is_symlink():
                raise DomainError(409, "个人记忆目录不能经过符号链接")

    def _repository(self, employee_id, *, create=False):
        try:
            employee_id = str(UUID(employee_id))
        except ValueError as exc:
            raise DomainError(400, "员工标识无效") from exc
        directory = self.root / "employees" / employee_id
        self._safe(directory)
        if not directory.exists() and create:
            directory.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = Path(tempfile.mkdtemp(prefix=".memory-", dir=directory.parent))
            try:
                self._git(temporary, "init", "--bare", str(temporary / ".git"), git_dir=False)
                try:
                    temporary.rename(directory)
                except OSError as exc:
                    if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                        raise
                    # 并发初始化只接受已经存在的完整仓库，不覆盖它。
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        if not directory.exists():
            raise DomainError(409, "记忆索引指向的 Git 仓库缺失，需要恢复备份")
        self._safe(directory / ".git")
        if not (directory / ".git/objects").is_dir():
            raise DomainError(409, "个人记忆 Git 仓库损坏")
        # 不允许 alternate 对象库把其他员工内容带入此仓库。
        if (directory / ".git/objects/info/alternates").exists():
            raise DomainError(409, "个人记忆禁止跨仓库对象引用")
        return directory

    @staticmethod
    def _git(directory, *args, data=None, git_dir=True):
        # 忽略主机 Git 环境与 hooks；调用者输入只能进入 stdin 或受校验的对象 ID。
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Astra Memory",
            GIT_AUTHOR_EMAIL="memory@astra.invalid",
            GIT_COMMITTER_NAME="Astra Memory",
            GIT_COMMITTER_EMAIL="memory@astra.invalid",
            GIT_AUTHOR_DATE=f"{now()} +0000",
            GIT_COMMITTER_DATE=f"{now()} +0000",
        )
        command = ["git", "-c", f"core.hooksPath={os.devnull}"]
        if git_dir:
            command += [f"--git-dir={directory / '.git'}"]
        try:
            result = subprocess.run(
                [*command, *args], input=data, capture_output=True, env=env, timeout=15, check=True
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DomainError(409, "Git Memory 操作失败，请检查存储或恢复备份") from exc
        return result.stdout

    def read(self, employee_id, head):
        self._head(head)
        if head is None:
            return {"content": "", "notes": {}, "source_refs": [], "expires_at": None, "expired": False}
        directory = self._repository(employee_id)
        try:
            manifest = json.loads(self._git(directory, "show", f"{head}:memory.json"))
            content = self._git(directory, "show", f"{head}:MEMORY.md").decode()
            notes = {
                name: self._git(directory, "show", f"{head}:notes/{name}").decode()
                for name in manifest["notes"]
                if NOTE.fullmatch(name)
            }
        except (ValueError, KeyError, UnicodeError) as exc:
            raise DomainError(409, "个人记忆版本内容损坏") from exc
        return {
            "content": content,
            "notes": notes,
            "source_refs": manifest["source_refs"],
            "expires_at": manifest["expires_at"],
            "expired": bool(manifest["expires_at"] and manifest["expires_at"] <= now()),
            "actor_id": manifest["actor_id"],
            "reason": manifest["reason"],
            "created_at": manifest.get("created_at"),
        }

    def prepare(self, employee_id, data, *, actor_id, identity, operation_key):
        self._head(data.expected_head)
        if len(data.content.encode()) > 16000 or sum(len(v.encode()) for v in data.notes.values()) > 64000:
            raise DomainError(400, "核心记忆最多 16 KB，详细笔记总计最多 64 KB")
        if len(data.notes) > 20 or any(not NOTE.fullmatch(name) for name in data.notes):
            raise DomainError(400, "笔记仅接受最多 20 个小写字母、数字或下划线命名的 md 文件")
        directory = self._repository(employee_id, create=True)
        if data.expected_head:
            self._git(directory, "cat-file", "-e", f"{data.expected_head}^{{commit}}")
        manifest = {
            "actor_id": actor_id,
            "operation_key": operation_key,
            "source_refs": data.source_refs,
            "expires_at": data.expires_at,
            "reason": data.reason,
            "notes": sorted(data.notes),
        }
        request_hash = hashlib.sha256(
            json.dumps([manifest, data.model_dump(), identity], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        prepared_ref = f"refs/prepared/{request_hash}"
        existing = (
            self._git(directory, "for-each-ref", "--format=%(objectname)", prepared_ref).decode().strip()
        )
        if existing:
            return existing
        manifest["created_at"] = now()

        def blob(content):
            output = self._git(directory, "hash-object", "-w", "--stdin", data=content.encode())
            return output.decode().strip()

        rows = [
            f"100644 blob {blob(identity)}\tIDENTITY.md\n",
            f"100644 blob {blob(data.content)}\tMEMORY.md\n",
            f"100644 blob {blob(json.dumps(manifest, ensure_ascii=False, sort_keys=True))}\tmemory.json\n",
        ]
        if data.notes:
            notes = "".join(
                f"100644 blob {blob(value)}\t{name}\n" for name, value in sorted(data.notes.items())
            )
            tree = self._git(directory, "mktree", data=notes.encode()).decode().strip()
            rows.append(f"040000 tree {tree}\tnotes\n")
        tree = self._git(directory, "mktree", data="".join(sorted(rows)).encode()).decode().strip()
        args = ["commit-tree", tree]
        if data.expected_head:
            args += ["-p", data.expected_head]
        head = self._git(directory, *args, data=data.reason.encode()).decode().strip()
        # 内容保存引用只防 GC；业务可见性只看数据库 head 和其祖先。
        self._git(directory, "update-ref", f"refs/content/{head}", head)
        try:
            self._git(directory, "update-ref", prepared_ref, head, "0" * 40)
        except DomainError:
            # 相同内容的并发准备只确定一个不可变对象，不代表业务已经发布。
            existing = (
                self._git(directory, "for-each-ref", "--format=%(objectname)", prepared_ref).decode().strip()
            )
            if not existing:
                raise
            return existing
        return head

    def history(self, employee_id, head):
        self._head(head)
        if head is None:
            return []
        directory = self._repository(employee_id)
        ids = self._git(directory, "rev-list", "--max-count=50", head).decode().splitlines()
        return [{"head": value, **self.read(employee_id, value)} for value in ids]

    def diff(self, employee_id, head, previous):
        self._head(head)
        self._head(previous)
        if head is None or previous is None:
            raise DomainError(400, "版本对比必须指定两个已提交版本")
        directory = self._repository(employee_id)
        ids = self._git(directory, "rev-list", head).decode().splitlines()
        if previous not in ids:
            raise DomainError(403, "只能对比当前记忆历史中的版本")
        return self._git(directory, "diff", previous, head, "--", "MEMORY.md", "notes").decode()
