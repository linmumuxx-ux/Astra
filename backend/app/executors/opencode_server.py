from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.executors.base import ExecutorResult, OpenCodeExecutor
from app.executors.errors import (
    OpenCodeExecutionError,
    OpenCodeExecutionTimeout,
    OpenCodeServerUnavailable,
    OpenCodeSessionNotFound,
)
from app.executors.opencode_prompt import build_task_prompt
from app.executors.usage import parse_opencode_usage
from app.models import Run, Task
from app.runtime.failure import FailureCode
from app.runtime.opencode_server import OpenCodeServerManager

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]
SessionCallback = Callable[[str], Awaitable[None]]
WorkspacePath = Path | PurePosixPath


class OpenCodeServerCapabilityError(RuntimeError):
    pass


def split_model(value: str | None) -> tuple[str, str] | None:
    if not value:
        return None
    provider, separator, model = value.partition("/")
    if not separator or not provider or not model:
        raise ValueError(f"OpenCode 模型必须使用 provider/model 格式：{value}")
    return provider, model


def normalize_server_event(event: dict[str, Any], *, agent_name: str | None = None) -> dict[str, Any]:
    properties = event.get("properties") if isinstance(event.get("properties"), dict) else {}
    normalized = {
        "type": event.get("type"),
        "serverEventID": event.get("id"),
        **properties,
    }
    part = normalized.get("part")
    if isinstance(part, dict) and agent_name and not part.get("agent"):
        normalized["part"] = {**part, "agent": agent_name}
    if agent_name and not normalized.get("agent"):
        normalized["agent"] = agent_name
    return normalized


def server_event_session_id(event: dict[str, Any]) -> str | None:
    properties = event.get("properties") if isinstance(event.get("properties"), dict) else {}
    part = properties.get("part") if isinstance(properties.get("part"), dict) else {}
    info = properties.get("info") if isinstance(properties.get("info"), dict) else {}
    return str(properties.get("sessionID") or part.get("sessionID") or info.get("sessionID") or "") or None


class OpenCodeServerClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        base_url: str | None = None,
        auth: httpx.BasicAuth | None = None,
        timeout_seconds: int | None = None,
    ):
        self.settings = settings or get_settings()
        self.manager = OpenCodeServerManager(self.settings)
        self.base_url = (base_url or self.manager.base_url).rstrip("/")
        self._auth = auth if base_url else self.manager.auth
        self._timeout_seconds = timeout_seconds or self.settings.opencode_timeout_seconds

    @property
    def auth(self) -> httpx.BasicAuth | None:
        return self._auth

    def _timeout(self, *, stream: bool = False) -> httpx.Timeout:
        return httpx.Timeout(
            None if stream else self._timeout_seconds,
            connect=10,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        directory: WorkspacePath | None = None,
        body: Any = None,
    ) -> Any:
        params = {"directory": str(directory)} if directory else None
        try:
            async with httpx.AsyncClient(auth=self.auth, timeout=self._timeout()) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    params=params,
                    json=body,
                )
        except httpx.TimeoutException as exc:
            raise OpenCodeExecutionTimeout(str(exc)) from exc
        except httpx.TransportError as exc:
            raise OpenCodeServerUnavailable(str(exc)) from exc
        if response.status_code == 404 and path.startswith("/session/") and path != "/session/status":
            raise OpenCodeSessionNotFound(path.split("/")[2])
        if response.status_code >= 500:
            raise OpenCodeServerUnavailable(f"OpenCode HTTP {response.status_code}")
        if response.is_error:
            raise OpenCodeExecutionError(f"OpenCode HTTP {response.status_code}: {response.text[:1000]}")
        return response.json() if response.content else None

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(auth=self.auth, timeout=3) as client:
                response = await client.get(f"{self.base_url}/global/health")
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OpenCodeServerUnavailable(f"OpenCode Server 不可用: {exc}") from exc
        version = str(payload.get("version") or "") or None
        if version and OpenCodeServerManager._version_tuple(version) < OpenCodeServerManager._version_tuple(
            self.settings.opencode_server_min_version
        ):
            raise OpenCodeServerCapabilityError(
                f"OpenCode {version} 低于已验证的最低版本 {self.settings.opencode_server_min_version}"
            )
        if payload.get("healthy") is not True:
            raise OpenCodeServerCapabilityError(
                f"OpenCode Server 健康检查失败: {json.dumps(payload, ensure_ascii=False)}"
            )
        return {"healthy": True, "version": version}

    async def events(self, directory: WorkspacePath) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(auth=self.auth, timeout=self._timeout(stream=True)) as client:
            async with client.stream(
                "GET",
                f"{self.base_url}/event",
                params={"directory": str(directory)},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = json.loads(line[6:])
                    if isinstance(payload, dict):
                        yield payload

    async def create_session(
        self,
        directory: WorkspacePath,
        *,
        title: str,
        model_name: str | None,
        agent: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "title": title,
            "metadata": {"astraRuntime": "opencode_server"},
            "permission": [{"permission": "*", "pattern": "*", "action": "allow"}],
        }
        model = split_model(model_name)
        if model:
            body["model"] = {"providerID": model[0], "id": model[1]}
        if agent:
            body["agent"] = agent
        return await self.request("POST", "/session", directory=directory, body=body)

    async def session(self, directory: WorkspacePath, session_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/session/{session_id}", directory=directory)

    async def prompt(
        self,
        directory: WorkspacePath,
        session_id: str,
        *,
        text: str,
        model_name: str | None,
        agent: str | None,
    ) -> None:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        model = split_model(model_name)
        if model:
            body["model"] = {"providerID": model[0], "modelID": model[1]}
        if agent:
            body["agent"] = agent
        await self.request(
            "POST",
            f"/session/{session_id}/prompt_async",
            directory=directory,
            body=body,
        )

    async def messages(self, directory: WorkspacePath, session_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", f"/session/{session_id}/message", directory=directory)

    async def children(self, directory: WorkspacePath, session_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", f"/session/{session_id}/children", directory=directory)

    async def questions(self, directory: WorkspacePath) -> list[dict[str, Any]]:
        return await self.request("GET", "/question", directory=directory)

    async def permissions(self, directory: WorkspacePath) -> list[dict[str, Any]]:
        return await self.request("GET", "/permission", directory=directory)

    async def reply_question(
        self,
        directory: WorkspacePath,
        request_id: str,
        answers: list[list[str]],
    ) -> bool:
        return bool(
            await self.request(
                "POST",
                f"/question/{request_id}/reply",
                directory=directory,
                body={"answers": answers},
            )
        )

    async def reply_permission(
        self,
        directory: WorkspacePath,
        request_id: str,
        reply: str,
    ) -> bool:
        return bool(
            await self.request(
                "POST",
                f"/permission/{request_id}/reply",
                directory=directory,
                body={"reply": reply},
            )
        )

    async def abort(self, directory: WorkspacePath, session_id: str) -> bool:
        return bool(await self.request("POST", f"/session/{session_id}/abort", directory=directory))

    async def status(self, directory: WorkspacePath, session_id: str) -> str:
        await self.session(directory, session_id)
        statuses = await self.request("GET", "/session/status", directory=directory)
        return str((statuses.get(session_id) or {"type": "idle"}).get("type"))


class OpenCodeServerExecutor(OpenCodeExecutor):
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model_name: str | None = None,
        event_callback: EventCallback | None = None,
        session_callback: SessionCallback | None = None,
        client: OpenCodeServerClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.model_name = model_name or self.settings.opencode_model
        self.event_callback = event_callback
        self.session_callback = session_callback
        self.client = client or OpenCodeServerClient(self.settings)
        self._active: dict[str, tuple[str, WorkspacePath]] = {}

    async def start(self, task: Task, workspace: WorkspacePath) -> ExecutorResult:
        return await self._execute(task, workspace)

    async def resume(self, task: Task, run: Run, workspace: WorkspacePath) -> ExecutorResult:
        session_id = task.current_session_id or run.opencode_session_id
        if not session_id:
            return await self._execute(task, workspace)
        return await self._execute(task, workspace, session_id=session_id)

    async def _execute(
        self,
        task: Task,
        workspace: WorkspacePath,
        *,
        session_id: str | None = None,
    ) -> ExecutorResult:
        resuming = bool(session_id)
        await self.client.health()
        queue: asyncio.Queue[dict[str, Any] | BaseException] = asyncio.Queue()
        ready = asyncio.Event()
        listener = asyncio.create_task(self._listen(workspace, queue, ready))
        output: list[dict[str, Any]] = []
        inquiry: dict[str, Any] | None = None
        error_message = ""
        child_agents: dict[str, str] = {}
        relevant_sessions: set[str] = set()
        baseline_errors: set[str] = set()
        try:
            await asyncio.wait_for(ready.wait(), timeout=10)
            if session_id:
                await self.client.session(workspace, session_id)
            else:
                created = await self.client.create_session(
                    workspace,
                    title=f"Astra {task.id}",
                    model_name=self.model_name,
                    agent=self.settings.opencode_agent or "build",
                )
                session_id = str(created["id"])
            relevant_sessions.add(session_id)
            self._active[task.id] = (session_id, workspace)
            if self.session_callback:
                await self.session_callback(session_id)
            baseline_errors = set(self._message_errors(await self.client.messages(workspace, session_id)))

            replied = await self._reply_pending_intervention(task, workspace)
            if not replied:
                prompt = build_task_prompt(
                    task,
                    workspace,
                    retry=resuming,
                    native_question=True,
                )
                await self.client.prompt(
                    workspace,
                    session_id,
                    text=prompt,
                    model_name=self.model_name,
                    agent=self.settings.opencode_agent or "build",
                )

            deadline = asyncio.get_running_loop().time() + self.settings.opencode_timeout_seconds
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    await self.client.abort(workspace, session_id)
                    error_message = "Agent execution timeout"
                    break
                item = await asyncio.wait_for(queue.get(), timeout=remaining)
                if isinstance(item, BaseException):
                    status = await self.client.status(workspace, session_id)
                    if status == "idle":
                        break
                    raise RuntimeError(f"OpenCode Event SSE 中断: {item}") from item
                event_type = str(item.get("type") or "")
                event_session = server_event_session_id(item)
                properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
                info = properties.get("info") if isinstance(properties.get("info"), dict) else {}

                if event_type == "session.created" and info.get("parentID") in relevant_sessions:
                    child_id = str(info.get("id") or properties.get("sessionID") or "")
                    if child_id:
                        relevant_sessions.add(child_id)
                        child_agents[child_id] = str(info.get("agent") or "Subagent")
                if event_session not in relevant_sessions:
                    continue

                normalized = normalize_server_event(
                    item,
                    agent_name=child_agents.get(str(event_session or "")),
                )
                if event_type != "message.part.delta":
                    output.append(normalized)
                    await self._emit(normalized)

                child_id = self._child_session_id(normalized)
                if child_id:
                    relevant_sessions.add(child_id)
                    child_agents.setdefault(child_id, self._child_agent(normalized))

                if event_type == "question.asked":
                    inquiry = self._question_inquiry(normalized)
                    break
                if event_type in {"permission.asked", "permission.updated"}:
                    inquiry = await self._permission_inquiry(workspace, normalized)
                    if inquiry:
                        break
                if event_type == "session.error" and event_session == session_id:
                    error_message = self._event_error(normalized)
                if event_type == "session.idle" and event_session == session_id:
                    break
        except OpenCodeSessionNotFound as exc:
            return ExecutorResult(
                status="FAILED",
                exit_code=1,
                session_id=exc.session_id,
                stderr=str(exc),
                failure_code=FailureCode.SESSION_NOT_FOUND,
            )
        except TimeoutError:
            if session_id:
                await self.client.abort(workspace, session_id)
            error_message = "Agent execution timeout"
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            self._active.pop(task.id, None)

        if not session_id:
            return ExecutorResult(status="FAILED", exit_code=1, stderr="OpenCode Session 创建失败")
        try:
            messages = await self.client.messages(workspace, session_id)
        except OpenCodeSessionNotFound as exc:
            return ExecutorResult(
                status="FAILED",
                exit_code=1,
                session_id=exc.session_id,
                output=output,
                stderr=str(exc),
                failure_code=FailureCode.SESSION_NOT_FOUND,
            )
        message_errors = [error for error in self._message_errors(messages) if error not in baseline_errors]
        if message_errors:
            error_message = error_message or "; ".join(message_errors)
        token_usage, tool_usage, detected_model = parse_opencode_usage(output)
        status = "WAITING_INPUT" if inquiry else "FAILED" if error_message else "SUCCEEDED"
        exit_code = 0
        if error_message and not inquiry and error_message != "Agent execution timeout":
            status = "FAILED"
            exit_code = 130 if "MessageAbortedError" in error_message else 1
        elif error_message == "Agent execution timeout":
            exit_code = 124
        return ExecutorResult(
            status=status,
            exit_code=exit_code,
            session_id=session_id,
            output=output,
            stderr=error_message,
            model_name=self.model_name or detected_model,
            inquiry=inquiry,
            token_usage=token_usage,
            tool_usage=tool_usage,
            failure_code=(
                FailureCode.EXECUTOR_TIMEOUT
                if exit_code == 124
                else FailureCode.SESSION_ERROR
                if exit_code
                else None
            ),
        )

    async def _listen(
        self,
        workspace: WorkspacePath,
        queue: asyncio.Queue[dict[str, Any] | BaseException],
        ready: asyncio.Event,
    ) -> None:
        attempts = 0
        while attempts < 3:
            try:
                async for event in self.client.events(workspace):
                    ready.set()
                    attempts = 0
                    await queue.put(event)
                attempts += 1
                if attempts >= 3:
                    ready.set()
                    await queue.put(RuntimeError("OpenCode Event SSE 已关闭"))
                    return
                await asyncio.sleep(0.25 * attempts)
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, OSError, ValueError) as exc:
                attempts += 1
                if attempts >= 3:
                    ready.set()
                    await queue.put(exc)
                    return
                await asyncio.sleep(0.25 * attempts)

    async def _emit(self, event: dict[str, Any]) -> None:
        if not self.event_callback:
            return
        try:
            await self.event_callback(event)
        except Exception:
            return

    async def _reply_pending_intervention(self, task: Task, workspace: WorkspacePath) -> bool:
        intervention = task.human_intervention or {}
        request_id = str(intervention.get("runtime_request_id") or "")
        kind = str(intervention.get("runtime_kind") or "")
        answer = str(intervention.get("response") or "").strip()
        if not request_id or not answer:
            return False
        if kind == "question":
            question_count = max(1, len(intervention.get("runtime_questions") or []))
            await self.client.reply_question(
                workspace,
                request_id,
                [[answer] for _ in range(question_count)],
            )
        elif kind == "permission":
            normalized = answer.lower()
            reply = (
                "reject"
                if any(value in normalized for value in ("reject", "deny", "拒绝", "不允许"))
                else "always"
                if any(value in normalized for value in ("always", "始终允许", "永久允许"))
                else "once"
            )
            await self.client.reply_permission(workspace, request_id, reply)
        else:
            return False
        task.human_intervention = {
            **intervention,
            "runtime_request_id": None,
            "runtime_replied_at": datetime.now(UTC).isoformat(),
        }
        return True

    @staticmethod
    def _question_inquiry(event: dict[str, Any]) -> dict[str, Any]:
        questions = event.get("questions") if isinstance(event.get("questions"), list) else []
        summaries = [str(item.get("question") or "").strip() for item in questions if isinstance(item, dict)]
        options = questions[0].get("options") if questions and isinstance(questions[0], dict) else []
        return {
            "blocking_reason": "OpenCode Agent 需要用户回答后继续当前 Session",
            "completed_work": "已保留当前 OpenCode Session 与执行现场",
            "current_state": "等待 OpenCode 原生 Question 回答",
            "requested_input": "\n".join(summaries) or "Agent 请求用户输入",
            "options": options if isinstance(options, list) else [],
            "runtime_kind": "question",
            "runtime_request_id": event.get("id"),
            "runtime_session_id": event.get("sessionID"),
            "runtime_questions": questions,
        }

    async def _permission_inquiry(
        self,
        workspace: WorkspacePath,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        session_id = str(event.get("sessionID") or "")
        requests = await self.client.permissions(workspace)
        request = next(
            (
                item
                for item in requests
                if str(item.get("id") or "") == str(event.get("id") or "")
                or (session_id and str(item.get("sessionID") or "") == session_id)
            ),
            None,
        )
        if not request:
            return None
        return self.permission_inquiry(request)

    @staticmethod
    def permission_inquiry(request: dict) -> dict:
        permission = str(request.get("permission") or request.get("type") or "Agent 操作")
        patterns = request.get("patterns") or request.get("pattern") or []
        return {
            "blocking_reason": f"OpenCode 请求操作权限：{permission}",
            "completed_work": "已保留当前 OpenCode Session 与执行现场",
            "current_state": "等待用户决定是否授权",
            "requested_input": f"是否允许 Agent 执行 {permission}？{patterns}",
            "options": [
                {"label": "允许一次", "value": "once"},
                {"label": "始终允许", "value": "always"},
                {"label": "拒绝", "value": "reject"},
            ],
            "runtime_kind": "permission",
            "runtime_request_id": request.get("id"),
            "runtime_session_id": request.get("sessionID"),
            "runtime_questions": [],
        }

    @staticmethod
    def _child_session_id(event: dict[str, Any]) -> str | None:
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
        value = metadata.get("sessionId") or metadata.get("session_id")
        return str(value) if value else None

    @staticmethod
    def _child_agent(event: dict[str, Any]) -> str:
        part = event.get("part") if isinstance(event.get("part"), dict) else {}
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        tool_input = state.get("input") if isinstance(state.get("input"), dict) else {}
        return str(
            tool_input.get("subagent_type")
            or tool_input.get("subagentType")
            or tool_input.get("agent")
            or "Subagent"
        )

    @staticmethod
    def _event_error(event: dict[str, Any]) -> str:
        error = event.get("error")
        if isinstance(error, dict):
            data = error.get("data") if isinstance(error.get("data"), dict) else {}
            return str(data.get("message") or error.get("message") or error.get("name") or "")
        return str(error or "")

    @staticmethod
    def _message_errors(messages: list[dict[str, Any]]) -> list[str]:
        errors: list[str] = []
        for message in messages:
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            error = info.get("error")
            if isinstance(error, dict):
                name = str(error.get("name") or "AgentError")
                data = error.get("data") if isinstance(error.get("data"), dict) else {}
                detail = str(data.get("message") or error.get("message") or "")
                errors.append(f"{name}: {detail}".rstrip(": "))
        return errors

    async def pending_inquiry(self, client, workspace, session_id) -> dict | None:
        for request in await client.questions(workspace):
            if request.get("sessionID") == session_id:
                return self._question_inquiry(request)
        for request in await client.permissions(workspace):
            if request.get("sessionID") == session_id:
                return self.permission_inquiry(request)
        return None

    async def get_status(self, run: Run) -> str:
        session_id = run.opencode_session_id
        snapshot = run.execution_environment_snapshot or {}
        workspace_value = snapshot.get("workspace_root")
        if not session_id or not workspace_value:
            return run.status
        workspace = self.settings.employee_workspace_path(workspace_value)
        inquiry = await self.pending_inquiry(self.client, workspace, session_id)
        if inquiry:
            return "WAITING_INPUT"
        return (await self.client.status(workspace, session_id)).upper()

    async def abort(self, run: Run) -> None:
        active = self._active.get(run.task_id)
        if active:
            await self.client.abort(active[1], active[0])
            return
        if run.opencode_session_id:
            workspace_value = (run.execution_environment_snapshot or {}).get("workspace_root")
            if workspace_value:
                workspace = self.settings.employee_workspace_path(workspace_value)
                await self.client.abort(workspace, run.opencode_session_id)

    async def collect_result(self, run: Run) -> dict[str, Any]:
        existing = run.result or {}
        if existing.get("work_result"):
            return existing
        session_id = run.opencode_session_id
        workspace_value = (run.execution_environment_snapshot or {}).get("workspace_root")
        if not session_id or not workspace_value:
            return existing
        workspace = self.settings.employee_workspace_path(workspace_value)
        inquiry = await self.pending_inquiry(self.client, workspace, session_id)
        if inquiry:
            return {"inquiry": inquiry}
        messages = await self.client.messages(workspace, session_id)
        return self.recovered_message_result(run, messages, existing)

    @classmethod
    def recovered_message_result(cls, run: Run, messages: list[dict], existing: dict) -> dict:
        latest = next(
            (item for item in reversed(messages) if (item.get("info") or {}).get("role") == "assistant"), None
        )
        if latest and cls._message_errors([latest]):
            return {
                "failure_code": FailureCode.SESSION_ERROR,
                "raw_error": "; ".join(cls._message_errors([latest])),
            }
        # A previous turn's text cannot complete a newer prompt after Worker loss.
        created = ((latest or {}).get("info") or {}).get("time", {}).get("created")
        boundary = run.queued_at or run.started_at
        if boundary and (not created or float(created) / 1000 < boundary.timestamp()):
            return {}
        raw_text = cls._last_assistant_message(messages[-1:] if latest is None else [latest])
        return {**existing, "raw_text": raw_text} if raw_text else existing

    @staticmethod
    def _last_assistant_message(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            info = message.get("info") if isinstance(message.get("info"), dict) else {}
            if str(info.get("role") or "").lower() != "assistant":
                continue
            parts = message.get("parts") if isinstance(message.get("parts"), list) else []
            texts = [
                str(part.get("text") or "").strip()
                for part in parts
                if isinstance(part, dict)
                and str(part.get("type") or "").lower() == "text"
                and str(part.get("text") or "").strip()
            ]
            if texts:
                return "\n".join(texts)
        return ""
