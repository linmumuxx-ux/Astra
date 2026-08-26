import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.models import Task


class WorkspaceManager:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    async def create(self, task: Task, *, copy_source: bool = True) -> Path:
        root = self.settings.workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        workspace = (root / task.id).resolve()
        if root not in workspace.parents:
            raise ValueError("Invalid task workspace")
        for name in ("source", "output", "evidence", "logs", "meta"):
            (workspace / name).mkdir(parents=True, exist_ok=True)

        project_path = task.input.get("project_path")
        source_dir = workspace / "source"
        if copy_source and project_path and not any(source_dir.iterdir()):
            project = Path(project_path).expanduser().resolve()
            if not project.is_dir():
                raise FileNotFoundError(f"任务工程不存在: {project}")
            if (project / ".git").exists():
                process = await asyncio.create_subprocess_exec(
                    "git",
                    "clone",
                    "--local",
                    "--no-hardlinks",
                    str(project),
                    str(source_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await process.communicate()
                if process.returncode:
                    raise RuntimeError(stderr.decode("utf-8", errors="replace"))
            else:
                shutil.copytree(
                    project,
                    source_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(".env", "*.pem", "*.key", "node_modules", ".venv"),
                )

        metadata = {
            "task_id": task.id,
            "source": task.source,
            "external_task_id": task.external_task_id,
            "created_at": datetime.now(UTC).isoformat(),
        }
        (workspace / "meta" / "task.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return workspace
