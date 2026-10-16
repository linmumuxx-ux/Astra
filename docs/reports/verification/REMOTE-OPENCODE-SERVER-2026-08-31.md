# Linux 远程 OpenCode Server 适配（2026-08-31）

## 结论

**代码适配：PASS；真实 Linux SSH 主机 E2E：UNVERIFIED。**

Linux 远程不再默认执行 `opencode run --format json`。当 `ASTRA_EXECUTOR_TYPE=opencode_server` 时，Coordinator 选择 `RemoteOpenCodeServerExecutor`，Run 标记为 `opencode_server_ssh`，并通过 Paramiko SSH Tunnel 使用远程真实 Session / Event API。只有显式选择 `opencode_cli_fallback` 时才使用旧 `opencode_cli_fallback_ssh`。

本次仓库现场没有配置可认证的 Linux SSH 目标：演示环境只有占位 Host，数据库没有 SSH 密码，也没有可用的本机 SSH daemon 或容器运行时。因此没有伪造远程 E2E 的 PASS。OpenCode 1.18.25 + `opencode/glm-5.1` 的真实 Server 能力由同日 POC 和 Coordinator 烟测覆盖；远程传输层由可控的 TCP 转发、生命周期与执行器集成测试覆盖。

## 远程运行映射

```text
Celery / Coordinator
        → Paramiko SSH（密码认证）
        → 本机 127.0.0.1:临时端口
        → SSH direct-tcpip
        → Linux 127.0.0.1:<员工 Server Port>
        → opencode serve
        → Session / Message / Event / Child / Question / Abort
```

- Server 未启动时：远程执行 `nohup <opencode_path> serve --hostname 127.0.0.1 --port <port>`。
- 日志/PID：`/tmp/astra-opencode-server-<uid>-<port>/`。
- Workspace：API `directory` 始终使用远程 `PurePosixPath`，不经过 Astra 主机路径解析。
- Resume / Question Reply / Abort：重新建立短期 SSH Tunnel，继续原 Session ID。
- 并发：各 Run 使用独立 Tunnel；Server Event 继续按主/子 Session ID 分流。
- 安全：远程 Server 不监听公网；SSH 密码不进入快照，Server Port 会进入快照。

## 自动验证结果

| 验证项 | 结果 |
|---|---|
| 正式模式选择远程 Server Executor | PASS |
| 显式 fallback 仍选择远程 CLI | PASS |
| SSH 本地 loopback TCP 转发 | PASS |
| Server 只绑定远程 `127.0.0.1` | PASS |
| Server 未运行时自动启动并等待健康 | PASS |
| 远程中文/空格 POSIX Workspace 传递 | PASS |
| 结构化 Event 驱动执行结果 | PASS |
| Tunnel / SSH 连接回收 | PASS |
| Server Port API、快照与数据库迁移 | PASS |
| Ruff | PASS |
| Backend | 67 passed |
| Vue TypeScript / production build | PASS |
| 真实 Linux SSH 主机 | UNVERIFIED（缺少目标与凭据） |

## Linux 现场复验

在配置中心为一个员工填写真实 Linux Host、SSH Port、Username、密码、OpenCode 路径、绝对 Workspace 和独立 Server Port，保存后执行“测试连接”。检查项必须全部通过，并出现：

```text
OpenCode Server  PASS  OpenCode 1.18.25 · SSH loopback tunnel
```

随后至少执行普通 Tool、Subagent、Question/Reply、同 Session 第二轮、Abort 和两个并发 Task。Run 的 `executor_type` 必须是 `opencode_server_ssh`，且远程主机只应有 loopback 监听，不应开放 Server Port。
