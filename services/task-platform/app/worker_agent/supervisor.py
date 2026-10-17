"""OpenCode 进程监督占位。

通信断开是网络故障。OpenCode 健康时不得因为 WebSocket 断开而重启。
阶段 1 不拉起 OpenCode 进程；进程退出与断线是两条分开的路径。
"""


class RuntimeSupervisor:
    def __init__(self) -> None:
        self.restart_count = 0

    def on_connection_lost(self) -> None:
        return

    def on_process_exit(self, _code: int) -> None:
        self.restart_count += 1
