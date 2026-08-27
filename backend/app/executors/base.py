from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Run, Task


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    total_tokens: int | None = None
    llm_call_count: int | None = None


@dataclass(slots=True)
class ToolUsageResult:
    name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    duration_ms: int = 0


@dataclass(slots=True)
class ExecutorResult:
    status: str
    exit_code: int
    session_id: str | None = None
    output: list[dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    model_name: str | None = None
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tool_usage: list[ToolUsageResult] = field(default_factory=list)


class CLIExecutor(ABC):
    @abstractmethod
    async def start(self, task: Task, workspace: Path) -> ExecutorResult: ...

    @abstractmethod
    async def resume(self, task: Task, run: Run, workspace: Path) -> ExecutorResult: ...

    @abstractmethod
    async def get_status(self, run: Run) -> str: ...

    @abstractmethod
    async def abort(self, run: Run) -> None: ...

    @abstractmethod
    async def collect_result(self, run: Run) -> dict[str, Any]: ...


# Backward-compatible import for the current OpenCode adapter. New CLI adapters
# should implement the neutral CLIExecutor contract.
OpenCodeExecutor = CLIExecutor
