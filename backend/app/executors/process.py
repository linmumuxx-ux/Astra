import asyncio
import os
import shutil
import subprocess
from pathlib import Path


def _strip_wrapping_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def resolve_executable(value: str) -> str | None:
    """Resolve a command name or an absolute executable path on the current OS."""

    command = _strip_wrapping_quotes(value)
    resolved = shutil.which(command)
    if resolved:
        return str(Path(resolved).resolve())

    candidate = Path(os.path.expandvars(command)).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return None


def local_command(executable: str, arguments: list[str]) -> list[str]:
    """Build argv without shell concatenation; adapt Windows batch launchers explicitly."""

    resolved = resolve_executable(executable)
    if not resolved:
        raise FileNotFoundError(f"未找到 Agent 可执行文件：{executable}")
    argv = [resolved, *arguments]
    if os.name == "nt" and Path(resolved).suffix.lower() in {".cmd", ".bat"}:
        comspec = os.environ.get("COMSPEC") or shutil.which("cmd.exe") or "cmd.exe"
        return windows_batch_command(resolved, arguments, comspec)
    return argv


def windows_batch_command(executable: str, arguments: list[str], comspec: str = "cmd.exe") -> list[str]:
    quoted = " ".join(_quote_for_cmd(argument) for argument in [executable, *arguments])
    return [comspec, "/d", "/s", "/c", quoted]


def _quote_for_cmd(argument: str) -> str:
    """Quote one cmd.exe argument, including real newlines and shell metacharacters."""

    if not argument:
        return '""'
    needs_quotes = any(
        character in argument for character in (" ", "\t", "\n", "\r", '"', "^", "&", "|", "<", ">", "(", ")")
    )
    if not needs_quotes:
        return argument

    # Follow the Windows C runtime quoting rules, but quote more characters
    # than subprocess.list2cmdline so cmd.exe cannot split multiline prompts.
    chunks = ['"']
    backslashes = 0
    for character in argument:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"':
            chunks.append("\\" * (backslashes * 2 + 1))
            chunks.append('"')
            backslashes = 0
            continue
        chunks.append("\\" * backslashes)
        chunks.append(character)
        backslashes = 0
    chunks.append("\\" * (backslashes * 2))
    chunks.append('"')
    return "".join(chunks)


def process_group_options() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def terminate_process(process: asyncio.subprocess.Process, timeout: int = 10) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe") or shutil.which("taskkill")
        if taskkill:
            killer = await asyncio.create_subprocess_exec(
                taskkill,
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            process.terminate()
    else:
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
