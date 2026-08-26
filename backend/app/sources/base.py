from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExternalTask:
    external_task_id: str
    task_type: str
    title: str
    description: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    definition_of_done: list[str] = field(default_factory=list)
    priority: str = "P2"


class TaskSource(ABC):
    id: str

    @abstractmethod
    async def discover_tasks(self) -> list[ExternalTask]: ...

    @abstractmethod
    async def get_task(self, external_task_id: str) -> ExternalTask: ...

    @abstractmethod
    async def update_task(self, external_task_id: str, result: dict[str, Any]) -> None: ...

    @abstractmethod
    async def heartbeat(self) -> bool: ...
