"""A task-bound native protocol gateway, not a second OpenCode API or UI implementation."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.routes import require_task
from app.database import get_session
from app.domain import ExecutionMode
from app.executors.errors import OpenCodeSessionNotFound
from app.models import RuntimeSession
from app.runtime.lifecycle import RuntimeService, RuntimeStateError
from app.runtime.session_connection import connect, resolve_environment
from app.runtime.workspace_files import MAX_UPLOAD, same_workspace_path, upload, validate_path
from app.schemas import TaskRead

router = APIRouter(prefix="/api/tasks/{task_id}")
# Task Workspace capability model: a task-bound, read-only window onto the
# employee's OpenCode server plus the native conversation/reply writes below.
# GET-only paths must be non-mutating and must not create PTYs, processes or
# sessions; anything capable of executing work is denied here and only reachable
# through an explicit task action. `/pty/shells` only lists shells for the native
# Settings page, so it stays read-only while `/pty` (PTY lifecycle) is faked empty.
READ_PATHS = {
    # Server / workspace observation
    "/global/health",
    "/project",
    "/project/current",
    "/path",
    "/vcs",
    "/vcs/diff",
    "/vcs/diff/raw",
    "/file",
    "/file/content",
    "/file/status",
    "/find",
    "/find/file",
    "/find/symbol",
    "/lsp",
    "/formatter",
    "/experimental/resource",
    "/experimental/worktree",
    # Native Settings (read-only)
    "/global/config",
    "/config",
    "/config/providers",
    "/provider",
    "/provider/auth",
    "/agent",
    "/command",
    "/skill",
    "/mcp",
    "/api/reference",
    "/pty/shells",
    # Conversation observation
    "/session",
    "/session/status",
    "/permission",
    "/question",
    "/pty",
}
SESSION_READ = re.compile(r"^/session/([^/]+)(/(children|todo|diff|message)(/[^/]+)?)?$")
SESSION_WRITE = re.compile(
    r"^/session/([^/]+)/(prompt_async|message|abort|revert|unrevert|summarize|command)$"
)
REPLY = re.compile(r"^/(question|permission)/([^/]+)/(reply|reject)$")


def error_response(exc):
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, OpenCodeSessionNotFound):
        return HTTPException(404, "Session 不存在；请显式选择恢复或新建 Session")
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    if isinstance(exc, (ValueError, RuntimeStateError)):
        return HTTPException(409, str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(409, f"Workspace 不存在：{exc}")
    return HTTPException(503, f"当前 OpenCode Runtime 不可连接：{exc}")


@router.post("/start", response_model=TaskRead)
async def start_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).start(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/restart", response_model=TaskRead)
async def restart_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).start(task_id, restart=True)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/stop", response_model=TaskRead)
async def stop_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).stop(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/reconnect", response_model=TaskRead)
async def reconnect_task(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).refresh(task_id)
    except Exception as exc:
        await session.rollback()
        await RuntimeService(session).disconnected(task_id, exc)
        raise error_response(exc) from exc


@router.get("/workspace")
async def task_workspace(task_id: str, session_id: str | None = None, session=Depends(get_session)):
    task = await require_task(task_id, session)
    bindings = (
        await session.scalars(
            select(RuntimeSession)
            .where(
                RuntimeSession.task_id == task.id,
            )
            .order_by(RuntimeSession.created_at.desc())
        )
    ).all()
    selected = next((item for item in bindings if item.id == (session_id or task.current_session_id)), None)
    if session_id and not selected:
        raise HTTPException(404, "Session 不属于此任务")
    return {
        "task_id": task.id,
        "task_status": task.status,
        "runtime": {
            "server": f"/api/tasks/{task.id}/opencode",
            "session_id": selected.id if selected else None,
            "workspace": selected.workspace if selected else task.workspace,
            "connection": task.runtime_connection,
            "error": task.runtime_error,
        },
        "sessions": [
            {
                "id": item.id,
                "workspace": item.workspace,
                "created_at": item.created_at,
                "status": item.status,
                "superseded_by": item.superseded_by,
                "finished_at": item.finished_at,
                "current": item.id == task.current_session_id,
            }
            for item in bindings
        ],
    }


@router.post("/files/{filename}")
async def upload_file(task_id: str, filename: str, request: Request, session=Depends(get_session)):
    task = await require_task(task_id, session)
    if not task.workspace:
        raise HTTPException(409, "任务尚未准备 Workspace")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_UPLOAD:
            raise HTTPException(413, "文件不能超过 20 MB")
    try:
        environment = await resolve_environment(session, task)
        path = await upload(environment, task.workspace, filename, bytes(content))
    except Exception as exc:
        raise error_response(exc) from exc
    return {"path": path}


async def session_tree(client, directory, root):
    allowed, pending = {root}, [root]
    while pending:
        children = await client.children(directory, pending.pop())
        for child in children:
            if child["id"] not in allowed:
                allowed.add(child["id"])
                pending.append(child["id"])
    return allowed


def event_session(event):
    props = event.get("properties", {})
    info = props.get("info", {})
    return (
        props.get("sessionID")
        or props.get("part", {}).get("sessionID")
        or info.get("sessionID")
        or (info.get("id") if event.get("type", "").startswith("session.") else None)
    )


async def native_events(environment, workspace, root, global_stream):
    async with connect(environment, start=True) as client:
        allowed = await session_tree(client, Path(workspace), root)
        async for event in client.events(Path(workspace)):
            props = event.get("properties", {})
            info = props.get("info", {})
            if event.get("type") == "session.created" and info.get("parentID") in allowed:
                allowed.add(info["id"])
            sid = event_session(event)
            if sid and sid not in allowed:
                continue
            if not sid and event.get("type") not in {
                "server.connected",
                "server.heartbeat",
                "file.edited",
                "file.watcher.updated",
                "vcs.branch.updated",
                "lsp.updated",
                "instance.disposed",
            }:
                continue
            value = {"directory": workspace, "payload": event} if global_stream else event
            yield f"data: {json.dumps(value, ensure_ascii=False)}\n\n"


async def persist_attachments(body, environment, workspace):
    for part in body.get("parts", []):
        if part.get("type") != "file":
            continue
        url = part.get("url", "")
        if url.startswith("data:"):
            header, encoded = url.split(",", 1)
            if ";base64" not in header or len(encoded) > MAX_UPLOAD * 4 // 3 + 8:
                raise ValueError("附件格式或大小无效")
            path = await upload(
                environment,
                workspace,
                part.get("filename") or "attachment",
                base64.b64decode(encoded, validate=True),
            )
            part["url"] = Path(path).as_uri()
        elif url.startswith("file:"):
            parsed = urlparse(url)
            if parsed.netloc:
                raise PermissionError("不允许外部文件地址")
            value = unquote(parsed.path)
            if environment.mode == ExecutionMode.LOCAL:
                value = url2pathname(value)
            await validate_path(environment, workspace, value)
        else:
            raise PermissionError("附件必须写入任务 Workspace")
    return body


@router.api_route("/opencode/{session_id}/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def native_proxy(
    task_id: str, session_id: str, path: str, request: Request, session=Depends(get_session)
):
    task = await require_task(task_id, session)
    binding = await session.get(RuntimeSession, session_id)
    if not binding or binding.task_id != task.id:
        raise HTTPException(404, "Session 不属于此任务")
    # Environment and directory are bound in the DB, never selected by browser-supplied paths.
    from app.models import OpenCodeExecutionEnvironment
    from app.runtime.environment import environment_from_snapshot

    environment = environment_from_snapshot(binding.environment, binding.employee_id)
    stored = await session.get(OpenCodeExecutionEnvironment, binding.environment["environment_id"])
    if stored:
        environment.ssh_password = stored.ssh_password
    workspace = binding.workspace
    if "workspace" in request.query_params or "x-opencode-workspace" in request.headers:
        raise HTTPException(403, "不允许覆盖任务绑定")
    for key, value in request.query_params.multi_items():
        if key.startswith("location") and (
            key != "location[directory]"
            or not same_workspace_path(environment, workspace, unquote(value))
        ):
            raise HTTPException(403, "不允许覆盖任务绑定")
    requested = request.query_params.get("directory") or request.headers.get("x-opencode-directory")
    requested_path = unquote(requested) if requested else None
    native_path = "/" + path
    directory = workspace
    if requested_path and not same_workspace_path(environment, workspace, requested_path):
        if request.method != "GET" or native_path not in {"/vcs/diff", "/vcs/diff/raw"}:
            raise HTTPException(403, "Workspace 不属于此任务")
        try:
            await validate_path(environment, workspace, requested_path)
        except Exception as exc:
            raise error_response(exc) from exc
        directory = requested_path
    method = request.method
    match = SESSION_READ.fullmatch(native_path) if method == "GET" else SESSION_WRITE.fullmatch(native_path)
    reply = REPLY.fullmatch(native_path) if method == "POST" else None
    if method != "GET" and session_id != task.current_session_id:
        raise HTTPException(403, "历史 Session 只读")
    if method == "GET" and native_path in {"/global/event", "/event"}:
        await session.commit()
        return StreamingResponse(
            native_events(environment, workspace, session_id, native_path == "/global/event"),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    if not match and not reply and not (method == "GET" and native_path in READ_PATHS):
        raise HTTPException(403, "此接口不属于 Task Workspace 的权限范围")
    try:
        await validate_path(environment, workspace, request.query_params.get("path", "."))
        async with connect(environment, start=True) as client:
            allowed = await session_tree(client, Path(workspace), session_id)
            # Global reads such as /session/status are not per-session resources;
            # their payloads are filtered to `allowed` below instead of rejected here.
            if match and native_path not in READ_PATHS and match[1] not in allowed:
                raise PermissionError("Session 不属于此任务")
            if method != "GET" and match and match[1] != session_id:
                raise PermissionError("子 Session 只读")
            body = json.loads(await request.body() or b"{}") if method != "GET" else None
            if body and {"directory", "sessionID", "workspace", "location"}.intersection(body):
                raise PermissionError("不允许覆盖任务绑定")
            if reply:
                items = await client.request("GET", f"/{reply[1]}", directory=Path(workspace))
                if not any(item["id"] == reply[2] and item.get("sessionID") in allowed for item in items):
                    raise PermissionError("请求不属于此任务 Session")
            if native_path.endswith(("/prompt_async", "/message", "/command")) and method == "POST":
                await persist_attachments(body, environment, workspace)
                await RuntimeService(session).send(
                    task.id,
                    body,
                    expected_session_id=session_id,
                    native_action="command" if native_path.endswith("/command") else "prompt_async",
                )
                return Response(status_code=204)
            if native_path.endswith("/abort") and method == "POST":
                await RuntimeService(session).stop(task.id)
                return True
            if native_path == "/pty":
                return []  # Arbitrary terminals are outside the task-scoped API boundary.
            params = dict(request.query_params)
            params["directory"] = directory
            if "location[directory]" in params:
                params["location[directory]"] = workspace
            for key in ("sessionID", "sessionId", "session_id"):
                if key in params and params[key] not in allowed:
                    raise PermissionError("Session 不属于此任务")
            forward_path = "/project/current" if native_path == "/project" else native_path
            async with httpx.AsyncClient(auth=client.auth, timeout=client._timeout()) as http:
                upstream = await http.request(
                    method, client.base_url + forward_path, params=params, json=body
                )
            if upstream.is_error:
                return Response(
                    content=upstream.content,
                    status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/json"),
                )
            if native_path == "/vcs/diff/raw":
                return Response(content=upstream.content, media_type="text/x-diff")
            data = upstream.json() if upstream.content else None
            if native_path == "/session":
                data = [item for item in data if item["id"] in allowed]
            elif native_path == "/session/status":
                data = {key: value for key, value in data.items() if key in allowed}
            elif native_path in {"/question", "/permission"}:
                data = [item for item in data if item.get("sessionID") in allowed]
            elif native_path in {"/project", "/project/current"}:
                data = {**data, "worktree": workspace, "sandboxes": []}
                if native_path == "/project":
                    data = [data]
            elif native_path == "/path":
                data = {
                    **data,
                    "directory": workspace,
                    "worktree": workspace,
                    "home": workspace,
                    "config": workspace,
                    "state": workspace,
                }
            elif native_path in {"/global/config", "/config"}:
                data = {
                    key: value
                    for key, value in data.items()
                    if key
                    in {
                        "snapshot",
                        "model",
                        "small_model",
                        "default_agent",
                        "username",
                        "enabled_providers",
                        "disabled_providers",
                    }
                }
                if environment.model_name:
                    data["model"] = environment.model_name
            elif native_path in {"/provider", "/config/providers"}:
                for provider in data.get("all", data.get("providers", [])):
                    for key in ("key", "options", "headers"):
                        provider.pop(key, None)
                    for model in provider.get("models", {}).values():
                        model["options"] = {}
                        model["headers"] = {}
            elif native_path == "/experimental/worktree":
                data = []
            if reply or method != "GET":
                await RuntimeService(session).refresh(task.id, client=client)
            return Response(
                content=json.dumps(data, ensure_ascii=False),
                media_type="application/json",
                headers={
                    key: value
                    for key, value in upstream.headers.items()
                    if key in {"link", "x-next-cursor", "x-has-more"}
                },
            )
    except Exception as exc:
        raise error_response(exc) from exc


@router.post("/retry-submission", response_model=TaskRead)
async def retry_submission(task_id: str, session=Depends(get_session)):
    await require_task(task_id, session)
    try:
        return await RuntimeService(session).retry_submission(task_id)
    except Exception as exc:
        raise error_response(exc) from exc


@router.get("/repo")
async def task_repo(task_id: str, session=Depends(get_session)):
    import asyncio
    import shlex

    from app.domain import ExecutionMode
    from app.runtime.environment import ExecutionEnvironmentRuntime

    task = await require_task(task_id, session)
    if not task.workspace:
        raise HTTPException(409, "Workspace 尚未准备")
    environment = await resolve_environment(session, task)
    await validate_path(environment, task.workspace, ".")

    async def git(*args):
        if environment.mode == ExecutionMode.LOCAL:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                task.workspace,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, _ = await proc.communicate()
            return output.decode().strip() if proc.returncode == 0 else ""
        code, output, _ = await ExecutionEnvironmentRuntime().run_remote(
            environment,
            shlex.join(["git", "-C", task.workspace, *args]),
        )
        return output.strip() if code == 0 else ""

    commit = await git("rev-parse", "HEAD")
    branch = await git("branch", "--show-current")
    changes = await git("status", "--porcelain")
    origin = await git("config", "--get", "remote.origin.url")
    common_dir = await git("rev-parse", "--path-format=absolute", "--git-common-dir")
    name = (
        origin.rstrip("/").split("/")[-1].removesuffix(".git")
        if origin
        else Path(common_dir).parent.name if common_dir else Path(task.workspace).name
    )
    return {
        "name": name,
        "branch": branch,
        "commit": commit,
        "dirty": bool(changes),
        "changes": len(changes.splitlines()),
    }
