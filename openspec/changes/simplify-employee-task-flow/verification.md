# 验证记录（2026-09-30）

基线：`refactor/dev-constraints-20260929`，`f7aed8b5094086c8420e8ce74d1e743bab9afbd9`。
开发分支：`fix/employee-task-flow-20260930`。

| 维度 | 结果 |
| --- | --- |
| 完整性 | 实施及静态/回归验证完成，4/5 tasks；真实业务验收待完成 |
| 正确性 | 3 项 Requirement 均有实现与回归覆盖；真实原生问答、权限及正常模型回复未验证 |
| 一致性 | 沿用 Task、RuntimeSession、Workspace 和 Element Plus；无新表、状态或编排层 |

## 实际执行

- 在 `backend/` 执行 `../.venv/bin/python -m ruff check app tests`：通过。
- 最终后端完整 `pytest -q --tb=short`：386 passed、4 skipped（复核增加停止后继续、旧 ACK 不干扰新轮次及历史工作区 Diff 绑定回归）；跳过项含 opt-in 真实 OpenCode 和外部 Gateway 验证，不能作为实测证据。
- 最终任务/工作区及后台恢复专项：103 passed；Ruff 再次通过。删除无调用的全量轮询和对应废弃配置。
- 最后调整远程配置复制后重跑工作区 shell 专项：6 passed。测试在本机执行真实 Git 和远程命令文本，未建立公司 SSH。
- 管理台 `npx vue-tsc -b`、`npx vite build`：通过；`playwright test --list` 加载 184 项用例。未修改或重建 `workspace-ui/`。
- `openspec validate simplify-employee-task-flow` 和 `git diff --check`：通过。

## 本机真实 OpenCode 1.2.27

使用实际 `opencode-ai@1.2.27` Server、实际 SQLite、RuntimeService、独立 Git worktree 和 Astra 原生 SSE 转发，无 Mock。选用不存在的 provider/model 验证确定性原生错误，不将其视为正常模型回复。

- Server health 返回版本 `1.2.27`；原生 SSE 收到 `server.connected`。
- 初始输入接受，第二次输入复用原 Session；原生消息列表恰有两条用户消息。
- Astra 全局 Workspace SSE 能转发绑定目录下的 `message.updated` 用户消息事件。
- 原生无回复错误后业务任务保留 WAITING，可再次输入；不自动成功。
- 项目 `permission.bash=ask` 在任务目录的原生 `/config` 中生效。
- 实际修改并提交文件后，累计 Diff 仍包含该文件。
- 原生空闲后人工确认，任务为 SUCCEEDED；后续 refresh 保持终态。

## 场景覆盖

| 场景 | 代码与回归证据 |
| --- | --- |
| 持续交流和人工结束 | `lifecycle.py`；`test_manual_confirm_allows_continuing_without_confirmation`、`test_completion_rejects_native_busy_and_pending_requests` |
| 原生问题、停止、失败、超时 | `workspace_routes.py`、`lifecycle.py`；子 Session 问题恢复、原生 abort、无回复及 timeout 测试 |
| 断线、重试、晚到 ACK | `recovery.py`、`lifecycle.py`；lost-ack、delayed-ack、supersede、断线、停止后继续及旧 ACK 不中断新轮专项；SSE 重连重新读取任务状态 |
| Worktree、配置、提交成果 | `session_connection.py`、`workspace_changes.py`；真实 Git 累计/当前 Diff、中文路径、配置及远程 shell 专项 |
| 简化创建及观察 | `schemas.py`、TaskCreateDrawer、store；现有 API 回归、busy/idle 消息读取与 supervisor 测试 |

## 归档前必须补齐（CRITICAL）

`tasks.md` 2.2 尚未完成：在有模型凭据和公司连接的环境执行真实业务验收。当前免费模型 CLI 请求返回 “OpenCode's free tier can only be used from within OpenCode”；没有正常模型回复的通过证据。

浏览器用例启动因 Chromium 缺失而失败；安装多次收到无效 ZIP。浏览器 UI、多轮正常模型回复、原生 question/permission 回答执行、真实断线重连不重复提交，以及公司 Windows / Linux SSH 的 1.2.27 流程均未实测。相关回归覆盖不替代这些验证。

未执行跨模块全量 `scripts/verify.py`，其中包含未修改原生前端的重建及当前无法启动的浏览器测试。本 change 保留待验收状态，不归档。
