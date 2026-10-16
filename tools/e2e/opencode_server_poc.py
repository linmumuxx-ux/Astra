#!/usr/bin/env python3
"""Run the Astra OpenCode Server gate against a real server and model.

The script intentionally uses only OpenCode's HTTP/SSE surface and the configured
model. It does not mock model replies, tools, sessions, or events.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CapabilityResult:
    status: str
    evidence: str


def split_model(value: str) -> tuple[str, str]:
    provider, separator, model = value.partition("/")
    if not separator or not provider or not model:
        raise ValueError("--model must use provider/model format")
    return provider, model


def event_session_id(event: dict[str, Any]) -> str | None:
    properties = event.get("properties") or {}
    part = properties.get("part") or {}
    info = properties.get("info") or {}
    return properties.get("sessionID") or part.get("sessionID") or info.get("sessionID")


def assistant_texts(messages: list[dict[str, Any]]) -> list[str]:
    return [
        str(part["text"])
        for message in messages
        if (message.get("info") or {}).get("role") == "assistant"
        for part in message.get("parts") or []
        if part.get("type") == "text" and part.get("text")
    ]


def tool_parts(messages: list[dict[str, Any]], tool: str | None = None) -> list[dict[str, Any]]:
    return [
        part
        for message in messages
        if (message.get("info") or {}).get("role") == "assistant"
        for part in message.get("parts") or []
        if part.get("type") == "tool" and (tool is None or part.get("tool") == tool)
    ]


class OpenCodeClient:
    def __init__(self, base_url: str, directory: Path, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.directory = directory.resolve()
        self.timeout = timeout

    def request(self, method: str, path: str, body: Any = None, *, scoped: bool = True) -> Any:
        query = urllib.parse.urlencode({"directory": str(self.directory)}) if scoped else ""
        separator = "&" if "?" in path else "?"
        url = f"{self.base_url}{path}{separator}{query}" if query else f"{self.base_url}{path}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = response.read()
        return json.loads(raw) if raw else None

    def create_session(self, title: str, provider: str, model: str) -> str:
        session = self.request(
            "POST",
            "/session",
            {
                "title": title,
                "model": {"id": model, "providerID": provider},
                "permission": [{"permission": "*", "pattern": "*", "action": "allow"}],
                "metadata": {"astraOpenCodeServerPoc": True},
            },
        )
        return str(session["id"])

    def prompt(self, session_id: str, text: str, provider: str, model: str) -> Any:
        return self.request(
            "POST",
            f"/session/{session_id}/message",
            {
                "model": {"providerID": provider, "modelID": model},
                "agent": "build",
                "parts": [{"type": "text", "text": text}],
            },
        )

    def prompt_async(self, session_id: str, text: str, provider: str, model: str) -> None:
        self.request(
            "POST",
            f"/session/{session_id}/prompt_async",
            {
                "model": {"providerID": provider, "modelID": model},
                "agent": "build",
                "parts": [{"type": "text", "text": text}],
            },
        )

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/session/{session_id}/message")

    def children(self, session_id: str) -> list[dict[str, Any]]:
        return self.request("GET", f"/session/{session_id}/children")

    def questions(self) -> list[dict[str, Any]]:
        return self.request("GET", "/question")

    def status(self, session_id: str) -> str:
        status = self.request("GET", "/session/status").get(session_id)
        return str((status or {"type": "idle"}).get("type"))

    def wait_idle(self, session_id: str, timeout: float | None = None) -> None:
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            if self.status(session_id) == "idle":
                return
            time.sleep(0.1)
        raise TimeoutError(f"session did not become idle: {session_id}")


class EventCollector:
    def __init__(self, client: OpenCodeClient):
        self.client = client
        self.events: list[dict[str, Any]] = []
        self.condition = threading.Condition()
        self.error: str | None = None
        self.thread = threading.Thread(target=self._listen, daemon=True)

    def start(self) -> None:
        self.thread.start()
        self.wait(lambda event: event.get("type") == "server.connected", timeout=10)

    def _listen(self) -> None:
        query = urllib.parse.urlencode({"directory": str(self.client.directory)})
        url = f"{self.client.base_url}/event?{query}"
        try:
            with urllib.request.urlopen(url, timeout=self.client.timeout * 4) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    with self.condition:
                        self.events.append(event)
                        self.condition.notify_all()
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            # The server shutdown normally closes the stream.
            self.error = str(exc)
            with self.condition:
                self.condition.notify_all()

    def wait(
        self,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self.condition:
            while True:
                match = next((event for event in self.events if predicate(event)), None)
                if match:
                    return match
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("expected SSE event was not observed")
                self.condition.wait(min(remaining, 0.25))

    def for_session(self, session_id: str) -> list[dict[str, Any]]:
        with self.condition:
            return [event for event in self.events if event_session_id(event) == session_id]


class ManagedServer:
    def __init__(self, binary: str, workspace: Path, timeout: float):
        self.binary = binary
        self.workspace = workspace
        self.timeout = timeout
        self.process: subprocess.Popen[str] | None = None
        self.base_url = ""
        self.log_lines: list[str] = []

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self) -> str:
        resolved = shutil.which(self.binary) or self.binary
        port = self.free_port()
        self.base_url = f"http://127.0.0.1:{port}"
        process_options: dict[str, Any] = {}
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_options["start_new_session"] = True
        self.process = subprocess.Popen(
            [resolved, "serve", "--hostname", "127.0.0.1", "--port", str(port)],
            cwd=self.workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_options,
        )
        deadline = time.monotonic() + min(self.timeout, 30)
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                output = self.process.stdout.read() if self.process.stdout else ""
                raise RuntimeError(f"opencode serve exited early: {output}")
            try:
                with urllib.request.urlopen(f"{self.base_url}/global/health", timeout=1) as response:
                    health = json.load(response)
                if health.get("healthy") is True:
                    return self.base_url
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                time.sleep(0.1)
        raise TimeoutError("opencode serve did not become healthy")

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


class Poc:
    def __init__(
        self,
        client: OpenCodeClient,
        events: EventCollector,
        provider: str,
        model: str,
        timeout: float,
    ):
        self.client = client
        self.events = events
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.results: dict[str, CapabilityResult] = {}

    def record(self, name: str, passed: bool, evidence: str) -> None:
        self.results[name] = CapabilityResult("PASS" if passed else "FAIL", evidence)

    def session(self, title: str) -> str:
        return self.client.create_session(f"Astra Server POC - {title}", self.provider, self.model)

    def run(self) -> dict[str, CapabilityResult]:
        first_session = self.agent_and_tool()
        self.multiturn(first_session)
        self.subagent()
        self.multiple_subagents()
        self.question_resume()
        self.abort()
        self.concurrent_isolation()
        self.results["windows_compatibility"] = CapabilityResult(
            "PASS" if os.name == "nt" else "UNVERIFIED",
            (
                f"real POC executed on Windows {sys.getwindowsversion()}"
                if os.name == "nt"
                else f"current host is {sys.platform}; rerun this script on deployed Windows host"
            ),
        )
        return self.results

    def agent_and_tool(self) -> str:
        session_id = self.session("agent and tool")
        self.client.prompt(
            session_id,
            "Use the bash tool exactly once to run pwd. Then reply exactly SERVER_POC_OK.",
            self.provider,
            self.model,
        )
        messages = self.client.messages(session_id)
        texts = assistant_texts(messages)
        tools = tool_parts(messages, "bash")
        session_events = self.events.for_session(session_id)
        text_events = [
            event
            for event in session_events
            if event.get("type") in {"message.part.updated", "message.part.delta"}
        ]
        tool_events = [
            event
            for event in session_events
            if (event.get("properties") or {}).get("part", {}).get("type") == "tool"
        ]
        self.record(
            "session_create",
            session_id.startswith("ses"),
            f"created {session_id} with {self.provider}/{self.model}",
        )
        self.record(
            "event_sse",
            bool(session_events),
            f"observed {len(session_events)} session-scoped SSE events",
        )
        self.record(
            "main_agent_message",
            "SERVER_POC_OK" in texts,
            f"assistant text markers: {texts[-2:]}",
        )
        self.record(
            "main_agent_tool",
            any((part.get("state") or {}).get("status") == "completed" for part in tools),
            f"bash tool parts={len(tools)}, text events={len(text_events)}, tool events={len(tool_events)}",
        )
        return session_id

    def multiturn(self, session_id: str) -> None:
        before = len(self.client.messages(session_id))
        self.client.prompt(
            session_id,
            "This is turn two. What exact marker did you return previously? "
            "Reply exactly TURN2_MEMORY:<marker>.",
            self.provider,
            self.model,
        )
        messages = self.client.messages(session_id)
        texts = assistant_texts(messages)
        self.record(
            "session_multiturn",
            len(messages) > before and "TURN2_MEMORY:SERVER_POC_OK" in texts,
            f"same {session_id}: messages {before}->{len(messages)}, final={texts[-1:]}",
        )

    def subagent(self) -> None:
        session_id = self.session("subagent child tool")
        self.client.prompt(
            session_id,
            "Use the task tool exactly once with subagent_type general. Ask the subagent to use "
            "the bash tool to run pwd and then return CHILD_TOOL_OK. Wait for it. Then reply "
            "exactly MAIN_CHILD_OK.",
            self.provider,
            self.model,
        )
        children = self.client.children(session_id)
        child = children[0] if len(children) == 1 else None
        child_messages = self.client.messages(child["id"]) if child else []
        child_text = assistant_texts(child_messages)
        child_tools = tool_parts(child_messages, "bash")
        child_events = self.events.for_session(str(child["id"])) if child else []
        self.record(
            "subagent_identification",
            bool(child and child.get("parentID") == session_id),
            f"parent={session_id}, children={[item.get('id') for item in children]}",
        )
        self.record(
            "subagent_result",
            "CHILD_TOOL_OK" in child_text,
            f"child final text={child_text[-1:]}",
        )
        self.record(
            "subagent_internal_tool",
            any((part.get("state") or {}).get("status") == "completed" for part in child_tools)
            and any(
                (event.get("properties") or {}).get("part", {}).get("tool") == "bash"
                for event in child_events
            ),
            f"child bash parts={len(child_tools)}, child events={len(child_events)}",
        )

    def multiple_subagents(self) -> None:
        session_id = self.session("multiple subagents")
        self.client.prompt(
            session_id,
            "Use the task tool twice: ask one general subagent to reply exactly CHILD_ALPHA, "
            "and a separate explore subagent to reply exactly CHILD_BETA. Wait for both. Then "
            "reply MULTI_CHILD_OK and include both exact markers.",
            self.provider,
            self.model,
        )
        children = self.client.children(session_id)
        outputs = {
            str(child.get("agent")): assistant_texts(self.client.messages(str(child["id"])))
            for child in children
        }
        passed = (
            len(children) == 2
            and any("CHILD_ALPHA" in texts for texts in outputs.values())
            and any("CHILD_BETA" in texts for texts in outputs.values())
        )
        self.record(
            "multiple_subagents",
            passed,
            f"children={[(child.get('id'), child.get('agent')) for child in children]}",
        )

    def question_resume(self) -> None:
        session_id = self.session("question and resume")
        self.client.prompt_async(
            session_id,
            "Use the question tool now to ask exactly one question: Which marker should I print? "
            "Offer BLUE and GREEN. After the user answers, reply exactly "
            "QUESTION_RESUMED:<selected answer>.",
            self.provider,
            self.model,
        )
        deadline = time.monotonic() + self.timeout
        question: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            question = next(
                (item for item in self.client.questions() if item.get("sessionID") == session_id),
                None,
            )
            if question:
                break
            time.sleep(0.1)
        if not question:
            self.record("native_question", False, "no native question request observed")
            self.record("question_resume", False, "cannot reply without a question request")
            return
        replied = self.client.request(
            "POST",
            f"/question/{question['id']}/reply",
            {"answers": [["BLUE"]]},
        )
        self.client.wait_idle(session_id)
        texts = assistant_texts(self.client.messages(session_id))
        event_types = {event.get("type") for event in self.events.for_session(session_id)}
        self.record(
            "native_question",
            "question.asked" in event_types,
            f"request={question['id']}, questions={len(question.get('questions') or [])}",
        )
        self.record(
            "question_resume",
            replied is True and "QUESTION_RESUMED:BLUE" in texts and "question.replied" in event_types,
            f"reply={replied}, final={texts[-1:]}, events={sorted(event_types & {'question.asked', 'question.replied'})}",
        )

    def abort(self) -> None:
        session_id = self.session("abort")
        self.client.prompt_async(
            session_id,
            "Use the bash tool now to run a command that waits for 120 seconds on this operating "
            "system. Do not skip the tool.",
            self.provider,
            self.model,
        )

        def running_bash(event: dict[str, Any]) -> bool:
            properties = event.get("properties") or {}
            part = properties.get("part") or {}
            state = part.get("state") or {}
            return (
                event_session_id(event) == session_id
                and part.get("type") == "tool"
                and part.get("tool") == "bash"
                and state.get("status") == "running"
            )

        try:
            self.events.wait(running_bash, timeout=self.timeout)
        except TimeoutError:
            self.record("abort", False, "bash tool never reached running state")
            return
        started = time.monotonic()
        aborted = self.client.request("POST", f"/session/{session_id}/abort")
        elapsed = time.monotonic() - started
        self.client.wait_idle(session_id)
        messages = self.client.messages(session_id)
        errors = [
            (message.get("info") or {}).get("error")
            for message in messages
            if (message.get("info") or {}).get("error")
        ]
        self.record(
            "abort",
            aborted is True and any(error.get("name") == "MessageAbortedError" for error in errors),
            f"abort returned {aborted} in {elapsed:.3f}s; errors={errors}",
        )

    def concurrent_isolation(self) -> None:
        sessions = {marker: self.session(f"concurrency {marker}") for marker in ("ALPHA", "BETA")}

        def execute(item: tuple[str, str]) -> tuple[str, Any]:
            marker, session_id = item
            reply = self.client.prompt(
                session_id,
                f"Reply exactly {marker}_FINAL. Never mention the other marker.",
                self.provider,
                self.model,
            )
            return marker, reply

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            dict(executor.map(execute, sessions.items()))
        passed = True
        evidence: list[str] = []
        for marker, session_id in sessions.items():
            foreign = "BETA" if marker == "ALPHA" else "ALPHA"
            messages = self.client.messages(session_id)
            texts = assistant_texts(messages)
            event_ids = {
                event_session_id(event) for event in self.events.for_session(session_id)
            }
            isolated = f"{marker}_FINAL" in texts and not any(foreign in text for text in texts)
            isolated = isolated and event_ids == {session_id}
            passed = passed and isolated
            evidence.append(f"{marker}={session_id}:{texts[-1:]}")
        self.record("concurrent_isolation", passed, "; ".join(evidence))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="reuse an already running opencode serve instance")
    parser.add_argument("--opencode-binary", default="opencode")
    parser.add_argument("--model", default="opencode/cat-jam-free")
    parser.add_argument("--workspace", type=Path, help="POC workspace; defaults to a temp directory")
    parser.add_argument("--timeout", type=float, default=180)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provider, model = split_model(args.model)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.workspace:
        workspace = args.workspace.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        temporary = tempfile.TemporaryDirectory(prefix="astra-opencode-server-poc-")
        workspace = Path(temporary.name)

    server: ManagedServer | None = None
    try:
        if args.base_url:
            base_url = args.base_url
        else:
            server = ManagedServer(args.opencode_binary, workspace, args.timeout)
            base_url = server.start()
        client = OpenCodeClient(base_url, workspace, args.timeout)
        health = client.request("GET", "/global/health", scoped=False)
        events = EventCollector(client)
        events.start()
        results = Poc(client, events, provider, model, args.timeout).run()
        core = [
            "session_create",
            "event_sse",
            "main_agent_message",
            "main_agent_tool",
            "subagent_identification",
            "subagent_result",
            "question_resume",
            "session_multiturn",
            "abort",
            "concurrent_isolation",
            "windows_compatibility",
        ]
        overall = all(results[name].status == "PASS" for name in core)
        payload = {
            "overall": "PASS" if overall else "FAIL",
            "server": health,
            "model": args.model,
            "host": {"platform": sys.platform, "os_name": os.name},
            "workspace": str(workspace),
            "capabilities": {name: asdict(result) for name, result in results.items()},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if overall else 1
    finally:
        if server:
            server.stop()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
