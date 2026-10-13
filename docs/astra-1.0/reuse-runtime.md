# OpenCode 成熟代码复用记录

固定参考基线：`05dd731`。新模块运行时不导入 `backend/app`、旧 Employee/Task、助手身份或旧 Settings。

| 原文件与算法 | 新位置 | 保留与清理 |
|---|---|---|
| `backend/app/executors/opencode_server.py` HTTP 控制请求、模型拆分、原生 Session/Message/Child/Question/Permission/Abort 接口 | `domains/runtime/client.py`、`config.py`、`sessions.py` | 保留成熟 Server/Session 协议；删除 ExecutorResult、旧 Task prompt、旧员工状态；用独立配置、明确错误和绑定核验接入 |
| `backend/app/assistant/client.py` 异步 prompt、BasicAuth 与 Session 包装 | `domains/runtime/client.py` | 提取通信协议；删除 platform-assistant 固定身份、PROJECT_ROOT、Settings；Persona/Task 配置独立，不保留旧助手 wrapper |
| `backend/app/runtime/session_connection.py` 原生 Session 树遍历 | `domains/runtime/client.py` 的 `session_tree` | 复用遍历，核验 parent 关系；只观察原生事实，不复制 transcript |
| `backend/app/runtime/session_connection.py` Git common-dir/worktree 注册核验、detach 创建、任务配置继承 | `domains/runtime/workspace.py` | 移除 Employee 目录和旧环境模型；按 TaskExecution 隔离，检查所有 symlink 父目录，恢复不重建、不覆盖未提交改动 |
| `backend/app/runtime/opencode_server.py` 健康与版本校验思路 | `domains/runtime/config.py`、`client.py` | 保留 `/global/health` 协议；精确部署版本与实时接口契约验证，不继承“版本更大即兼容”的推断 |
| `backend/app/assistant/review.py` 原生工具结果引用校验 | `domains/runtime/evidence.py` | 清理旧助手与旧 Task 依赖；校验原生树、非合成完成工具、原文与明确成功退出码，并绑定提交时片段 SHA256 |
| `backend/app/runtime/ssh_client.py` Paramiko 执行、SFTP、双向转发 | `domains/runtime/ssh.py` | 无旧领域依赖，改为固定 known_hosts/RejectPolicy；正确记录零端口分配结果；本机主机密钥握手及真实 Linux 转发执行验证 |

HTTP/SSE 错误不包含响应正文，防止工具输出或凭据进入日志。原生 SSE 改为完整事件块解析，支持 `data:`/`data: ` 与多行 JSON；有限内存去重只减少观察重复，不宣称端到端 exactly-once。原生 `/event` 没有业务持久化回放保证，重连后先读权威 Session；普通用户所用业务 SSE 由独立的业务事件序列负责。

Worker 调度、slot lease/fencing、共享资产锁和授权快照为 1.0 重新实现；未复制旧 `runtime/dispatcher.py` 的 Employee 容量算法。本地 Git 工作区、密码保护 OpenCode 工程执行及浏览器独立验收已真实验证。远程 SSH/进程启动的旧实现仍需在新 Credential/Grant 边界下提取，不将本机结果视为公司远程部署验收。

仓库原有文件的来源注释保留在新模块说明中。当前源文件无独立额外许可证头；若后续引入第三方代码，须单独核对许可证，不能因为旧文件可读而推断任意第三方代码可直接分发。
