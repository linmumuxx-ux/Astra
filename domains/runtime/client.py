"""从 0.xx 成熟通信层提取的 OpenCode HTTP/SSE 适配器。

原始来源：backend/app/executors/opencode_server.py、assistant/client.py。
不依赖旧 Settings/Employee/Task，不持久化消息，不重试具有未知副作用的写请求。
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from domains.runtime.config import OpenCodeConfig, RuntimePurpose, normalized_directory, split_model
from domains.runtime.errors import (
    NativeSessionNotFound,
    NativeSessionScopeError,
    OpenCodeAuthenticationError,
    OpenCodeEventStreamInterrupted,
    OpenCodeIncompatible,
    OpenCodeRequestRejected,
    OpenCodeUnavailable,
)
from domains.runtime.sessions import NativeSessionBinding, event_session_id, permission_digest

_REQUIRED_ENDPOINTS = {
    "/global/health": "get",
    "/event": "get",
    "/session": "post",
    "/session/status": "get",
    "/session/{sessionID}": "get",
    "/session/{sessionID}/message": "get",
    "/session/{sessionID}/children": "get",
    "/session/{sessionID}/prompt_async": "post",
    "/session/{sessionID}/abort": "post",
    "/question": "get",
    "/question/{requestID}/reply": "post",
    "/permission": "get",
    "/permission/{requestID}/reply": "post",
}


class OpenCodeClient:
    def __init__(self, config: OpenCodeConfig, *, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self._transport = transport
        self._ready = False

    def _http(self, *, stream: bool = False) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            self.config.stream_read_timeout_seconds if stream else self.config.control_timeout_seconds,
            connect=min(10, self.config.control_timeout_seconds),
        )
        auth = httpx.BasicAuth(self.config.username, self.config.password) if self.config.password else None
        return httpx.AsyncClient(
            auth=auth,
            timeout=timeout,
            verify=self.config.verify_tls,
            transport=self._transport,
            follow_redirects=False,
            trust_env=False,
        )

    @staticmethod
    def _check_response(response: httpx.Response, *, mutation: bool) -> None:
        code = response.status_code
        if code in {401, 403}:
            raise OpenCodeAuthenticationError(f"OpenCode 认证或服务访问被拒绝（HTTP {code}）")
        if code == 404:
            path = response.request.url.path
            if path.startswith("/session/") and path != "/session/status":
                raise NativeSessionNotFound("原生 OpenCode Session 不存在")
            raise OpenCodeIncompatible("OpenCode 未提供必要接口（HTTP 404）")
        if code >= 500:
            raise OpenCodeUnavailable(f"OpenCode 服务错误（HTTP {code}）", outcome_uncertain=mutation)
        if not 200 <= code < 300:
            # 响应可能含用户提示词、工具输出或密钥，不复制到异常及日志。
            raise OpenCodeRequestRejected(f"OpenCode 请求被拒绝（HTTP {code}）")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        directory: str | None = None,
        body: Any = None,
        query: dict[str, Any] | None = None,
        headers: bool = False,
    ) -> Any:
        params = dict(query or {})
        if directory is not None:
            params["directory"] = self.config.require_directory(directory)
        mutation = method not in {"GET", "HEAD", "OPTIONS"}
        try:
            async with self._http() as client:
                response = await client.request(
                    method,
                    self.config.base_url + path,
                    params=params,
                    json=body,
                )
        except httpx.TransportError as exc:
            raise OpenCodeUnavailable(
                "OpenCode 控制请求中断；写请求需先对账，禁止盲目重发",
                outcome_uncertain=mutation,
            ) from exc
        self._check_response(response, mutation=mutation)
        try:
            payload = response.json() if response.content else None
        except ValueError as exc:
            raise OpenCodeIncompatible("OpenCode 返回了非 JSON 响应") from exc
        return (payload, response.headers) if headers else payload

    async def health(self) -> dict[str, Any]:
        payload = await self._request("GET", "/global/health")
        if not isinstance(payload, dict) or payload.get("healthy") is not True:
            raise OpenCodeUnavailable("OpenCode 健康检查未通过")
        version = payload.get("version")
        if not isinstance(version, str) or version.removeprefix("v") not in {
            value.removeprefix("v") for value in self.config.compatible_versions
        }:
            raise OpenCodeIncompatible("OpenCode 版本未在部署契约的明确兼容版本中")
        return {"healthy": True, "version": version}

    async def verify_contract(self) -> dict[str, Any]:
        """只读验证实际服务接口；健康与版本通过并不代表模型执行通过。"""
        health = await self.health()
        document = await self._request("GET", "/doc")
        paths = document.get("paths", {}) if isinstance(document, dict) else {}
        missing = [path for path, method in _REQUIRED_ENDPOINTS.items() if method not in paths.get(path, {})]
        if missing:
            raise OpenCodeIncompatible("OpenCode 缺少必要 Session/Event/人工干预接口")
        try:
            schema = paths["/session"]["post"]["requestBody"]["content"]["application/json"]["schema"]
            properties = schema["properties"]
        except (KeyError, TypeError) as exc:
            raise OpenCodeIncompatible("OpenCode Session 创建契约无法核实") from exc
        if not {"metadata", "permission"}.issubset(properties):
            raise OpenCodeIncompatible("OpenCode Session 缺少身份隔离或权限限制能力")
        self._ready = True
        return {**health, "contract_verified": True}

    async def _ensure_ready(self) -> None:
        if not self._ready:
            await self.verify_contract()

    def _require_binding(self, binding: NativeSessionBinding) -> str:
        if binding.runtime_id != self.config.runtime_id or binding.purpose != self.config.purpose:
            raise NativeSessionScopeError("Session 不属于此 Runtime 身份或用途")
        return self.config.require_directory(binding.directory)

    def _metadata(self, owner_ref: str) -> dict[str, str]:
        return {
            "astraRuntime": "astra-1.0",
            "runtimeID": self.config.runtime_id,
            "purpose": self.config.purpose.value,
            "ownerRef": owner_ref,
        }

    @staticmethod
    def _session_path(native_session_id: str) -> str:
        if not native_session_id.startswith("ses"):
            raise ValueError("必须提供 OpenCode 原生 Session ID")
        return "/session/" + quote(native_session_id, safe="")

    async def create_session(
        self,
        directory: str,
        *,
        owner_ref: str,
        title: str,
        permission_rules: list[dict[str, str]] | None = None,
    ) -> NativeSessionBinding:
        """owner_ref 是后端的 PersonaTurn/TaskExecution ID，不能取自 Tool 自报身份。"""
        directory = self.config.require_directory(directory)
        if not owner_ref or not title:
            raise ValueError("Session 创建必须绑定业务索引和标题")
        await self._ensure_ready()
        if self.config.purpose is RuntimePurpose.PERSONA:
            if permission_rules is not None:
                raise ValueError("Persona Session 不接受调用者覆盖 Runtime 权限边界")
            permission_rules = self.config.persona_permissions()
        elif permission_rules is None:
            raise ValueError("Task Session 必须提供后端 Workspace/Task Grant 的权限快照")
        self._validate_permissions(permission_rules)
        body: dict[str, Any] = {
            "title": title,
            "metadata": self._metadata(owner_ref),
            "permission": permission_rules,
        }
        model = split_model(self.config.model)
        if model:
            body["model"] = {"providerID": model[0], "id": model[1]}
        if self.config.agent:
            body["agent"] = self.config.agent
        created = await self._request("POST", "/session", directory=directory, body=body)
        if not isinstance(created, dict) or not isinstance(created.get("id"), str):
            raise OpenCodeIncompatible("OpenCode Session 创建响应缺少原生 ID；请对账")
        binding = NativeSessionBinding(
            created["id"],
            self.config.runtime_id,
            self.config.purpose,
            owner_ref,
            directory,
            permission_digest(permission_rules),
        )
        self._validate_native_scope(binding, created)
        if created.get("permission") != permission_rules:
            raise OpenCodeIncompatible("OpenCode 未保留批准的权限快照；Session 不得开始执行")
        return binding

    @staticmethod
    def _validate_permissions(rules: list[dict[str, str]]) -> None:
        if not rules:
            raise ValueError("Task Grant 不得使用空权限快照（OpenCode 默认权限可能更宽）")
        for rule in rules:
            if set(rule) != {"permission", "pattern", "action"} or rule.get("action") not in {
                "allow",
                "deny",
                "ask",
            }:
                raise ValueError("OpenCode 权限规则无效")
            if not rule["permission"] or not rule["pattern"]:
                raise ValueError("OpenCode 权限规则必须含明确的 permission 与 pattern")

    def _validate_native_scope(self, binding: NativeSessionBinding, payload: dict[str, Any]) -> None:
        try:
            directory = normalized_directory(payload.get("directory", ""))
        except (ValueError, TypeError) as exc:
            raise NativeSessionScopeError("原生 Session 缺少可信目录绑定") from exc
        if payload.get("id") != binding.native_session_id or directory != binding.directory:
            raise NativeSessionScopeError("原生 Session ID 或目录与业务绑定不符")
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict) or any(
            metadata.get(key) != value for key, value in self._metadata(binding.owner_ref).items()
        ):
            raise NativeSessionScopeError("原生 Session 用途或主责索引与业务绑定不符")
        if (
            binding.purpose is RuntimePurpose.PERSONA
            and payload.get("permission") != self.config.persona_permissions()
        ):
            raise NativeSessionScopeError("Persona 原生 Session 权限已偏离决策边界")
        if binding.permission_digest:
            rules = payload.get("permission")
            if not isinstance(rules, list) or permission_digest(rules) != binding.permission_digest:
                raise NativeSessionScopeError("原生 Session 权限已偏离批准的 Task/Persona 快照")

    async def native_session(self, directory: str, native_session_id: str) -> dict[str, Any]:
        """供有历史证据授权的业务服务只读核验；不会补写历史 Session 的身份。"""
        payload = await self._request("GET", self._session_path(native_session_id), directory=directory)
        if not isinstance(payload, dict) or payload.get("id") != native_session_id:
            raise OpenCodeIncompatible("原生 Session 返回格式无效")
        if normalized_directory(payload.get("directory", "")) != self.config.require_directory(directory):
            raise NativeSessionScopeError("原生 Session 不属于批准目录")
        return payload

    async def session(self, binding: NativeSessionBinding) -> dict[str, Any]:
        directory = self._require_binding(binding)
        payload = await self.native_session(directory, binding.native_session_id)
        self._validate_native_scope(binding, payload)
        return payload

    async def prompt_async(self, binding: NativeSessionBinding, *, text: str, message_id: str) -> None:
        """message_id 由后端 operation 生成并持久化；断线后只对账、不自动重发。"""
        if not message_id.startswith("msg") or not text:
            raise ValueError("Prompt 需要稳定原生 message_id 和非空内容")
        if not binding.permission_digest:
            raise NativeSessionScopeError("发起执行前必须绑定批准的原生权限快照摘要")
        await self._ensure_ready()
        await self.session(binding)
        body: dict[str, Any] = {"messageID": message_id, "parts": [{"type": "text", "text": text}]}
        model = split_model(self.config.model)
        if model:
            body["model"] = {"providerID": model[0], "modelID": model[1]}
        if self.config.agent:
            body["agent"] = self.config.agent
        await self._request(
            "POST",
            self._session_path(binding.native_session_id) + "/prompt_async",
            directory=binding.directory,
            body=body,
        )

    async def messages(
        self,
        binding: NativeSessionBinding,
        *,
        limit: int = 100,
        before: str | None = None,
    ) -> dict[str, Any]:
        """即时读取原生消息；调用者不得把结果作为第二套 Transcript 持久化。"""
        if not 1 <= limit <= 1000:
            raise ValueError("原生消息分页大小必须介于 1 与 1000")
        await self.session(binding)
        query: dict[str, Any] = {"limit": limit}
        if before:
            query["before"] = before
        payload, response_headers = await self._request(
            "GET",
            self._session_path(binding.native_session_id) + "/message",
            directory=binding.directory,
            query=query,
            headers=True,
        )
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise OpenCodeIncompatible("OpenCode 原生消息格式无效")
        return {"messages": payload, "next_before": response_headers.get("x-next-cursor")}

    async def status(self, binding: NativeSessionBinding) -> dict[str, Any]:
        """仅返回原生活动状态。idle 不是 Task 成功，也不是业务终态。"""
        await self.session(binding)  # 不把不存在 Session 的 status 缺项误认成 idle。
        statuses = await self._request("GET", "/session/status", directory=binding.directory)
        if not isinstance(statuses, dict):
            raise OpenCodeIncompatible("OpenCode 原生状态格式无效")
        # 实时 /doc 的 SessionStatus 契约中，未列出的已存在 Session 为 idle。
        value = statuses.get(binding.native_session_id, {"type": "idle"})
        if not isinstance(value, dict) or value.get("type") not in {"idle", "busy", "retry"}:
            raise OpenCodeIncompatible("OpenCode 返回未知 Session 活动状态")
        return value

    async def abort(self, binding: NativeSessionBinding) -> bool:
        await self.session(binding)
        result = await self._request(
            "POST", self._session_path(binding.native_session_id) + "/abort", directory=binding.directory
        )
        if not isinstance(result, bool):
            raise OpenCodeIncompatible("OpenCode abort 返回格式无效；应查询原生 Session 对账")
        return result

    async def session_tree(self, binding: NativeSessionBinding) -> set[str]:
        # 复制旧 runtime/session_connection.py 的遍历，增加 parent 绑定检查。
        await self.session(binding)
        allowed, pending = {binding.native_session_id}, [binding.native_session_id]
        while pending:
            parent = pending.pop()
            children = await self._request(
                "GET", self._session_path(parent) + "/children", directory=binding.directory
            )
            if not isinstance(children, list):
                raise OpenCodeIncompatible("OpenCode 子 Session 格式无效")
            for child in children:
                if (
                    not isinstance(child, dict)
                    or child.get("parentID") != parent
                    or not isinstance(child.get("id"), str)
                ):
                    raise NativeSessionScopeError("OpenCode 子 Session 的 parent 绑定无法核实")
                if child["id"] not in allowed:
                    allowed.add(child["id"])
                    pending.append(child["id"])
        return allowed

    async def pending_interventions(self, binding: NativeSessionBinding) -> dict[str, list[dict[str, Any]]]:
        sessions = await self.session_tree(binding)
        result = {}
        for kind in ("question", "permission"):
            items = await self._request("GET", "/" + kind, directory=binding.directory)
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                raise OpenCodeIncompatible("OpenCode 人工干预格式无效")
            result[kind] = [item for item in items if item.get("sessionID") in sessions]
        return result

    async def reply_question(
        self, binding: NativeSessionBinding, request_id: str, *, answers: list[list[str]]
    ) -> bool:
        pending = await self.pending_interventions(binding)
        if not any(item.get("id") == request_id for item in pending["question"]):
            raise NativeSessionScopeError("问题不属于当前 Session 或已被处理")
        result = await self._request(
            "POST",
            "/question/" + quote(request_id, safe="") + "/reply",
            directory=binding.directory,
            body={"answers": answers},
        )
        if not isinstance(result, bool):
            raise OpenCodeIncompatible("OpenCode question reply 返回格式无效")
        return result

    async def reply_permission(
        self, binding: NativeSessionBinding, request_id: str, *, approved_once: bool
    ) -> bool:
        """仅在业务服务重新验证当前具体审批后调用；从不支持原生永久授权。"""
        if binding.purpose is RuntimePurpose.PERSONA:
            raise NativeSessionScopeError("Persona 不可通过 Runtime 人工授权扩大工具权限")
        pending = await self.pending_interventions(binding)
        if not any(item.get("id") == request_id for item in pending["permission"]):
            raise NativeSessionScopeError("权限请求不属于当前 Session 或已被处理")
        result = await self._request(
            "POST",
            "/permission/" + quote(request_id, safe="") + "/reply",
            directory=binding.directory,
            body={"reply": "once" if approved_once else "reject"},
        )
        if not isinstance(result, bool):
            raise OpenCodeIncompatible("OpenCode permission reply 返回格式无效")
        return result

    async def events(
        self, binding: NativeSessionBinding, *, include_children: bool = True
    ) -> AsyncIterator[dict[str, Any]]:
        """即时事件只作观察。断线后重新查询原生事实，不承诺 OpenCode SSE 回放。"""
        if include_children:
            sessions = await self.session_tree(binding)
        else:
            await self.session(binding)
            sessions = {binding.native_session_id}
        seen: deque[str] = deque(maxlen=1024)
        data: list[str] = []
        try:
            async with self._http(stream=True) as client:
                async with client.stream(
                    "GET", self.config.base_url + "/event", params={"directory": binding.directory}
                ) as response:
                    self._check_response(response, mutation=False)
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        raise OpenCodeIncompatible("OpenCode Event 未返回 SSE")
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            data.append(line[5:].removeprefix(" "))
                        elif not line and data:
                            try:
                                event = json.loads("\n".join(data))
                            except ValueError as exc:
                                raise OpenCodeIncompatible("OpenCode SSE data 不是有效 JSON") from exc
                            finally:
                                data = []
                            if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                                raise OpenCodeIncompatible("OpenCode SSE 事件格式无效")
                            properties = event.get("properties")
                            if not isinstance(properties, dict):
                                raise OpenCodeIncompatible("OpenCode SSE 缺少原生 properties")
                            info = properties.get("info", {})
                            if (
                                include_children
                                and event["type"] == "session.created"
                                and isinstance(info, dict)
                                and info.get("parentID") in sessions
                            ):
                                child = info.get("id")
                                if isinstance(child, str) and child.startswith("ses"):
                                    sessions.add(child)
                            if event_session_id(event) not in sessions:
                                continue
                            event_id = event.get("id")
                            if isinstance(event_id, str):
                                if event_id in seen:
                                    continue
                                seen.append(event_id)
                            yield event
        except httpx.TransportError as exc:
            raise OpenCodeEventStreamInterrupted("OpenCode SSE 中断；必须重新读取原生 Session 对账") from exc
        raise OpenCodeEventStreamInterrupted("OpenCode SSE 已关闭；必须重新读取原生 Session 对账")
