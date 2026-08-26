from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models import Run, Task


@dataclass(slots=True)
class ExecutorResult:
    status: str
    exit_code: int
    session_id: str | None = None
    output: list[dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""


class OpenCodeExecutor(ABC):
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
