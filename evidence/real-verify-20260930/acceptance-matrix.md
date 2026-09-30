# 六项验收矩阵（真实运行时，非 mock）

时间：2026-09-30。所有"真实"结论均来自本机真实 OpenCode Server **1.2.27** +
真实模型 `opencode/space-bunny-free` + 真实 Git worktree + 真实 SQLite，
浏览器结论来自 root 的真实 Chrome 操作记录。

## 1 创建任务分配员工自动启动，真实 1.2.27 正常模型回复

| 结论 | 证据 |
| --- | --- |
| 通过（修复后） | 见 `fixes.md` 第 1 条。修复前 root 真实浏览器与 API 双双停在「待执行 / 尚未创建 Session」；修复后同一页面自动变 `RUNNING`，并创建真实 Session `ses_f0d316562ffeaSckOd00zk1Brb` |
| 通过（我方 API 专项） | `T-20260930-FD4793` 创建后 25s 内 `RUNNING`，Session `ses_f0d2f9f14ffemfWDJO31Jv41xe`，首轮真实回复含 `write` 工具成功、`bash` 成功与 `od -c` 校验 |
| 通过（root 浏览器） | root 记录：首轮 UI 3 秒显示「首轮回复正常」，Task 保持 `RUNNING` 且输入可用（root 的真实 Chrome 会话） |

## 2 多轮交流复用当前 Session，单轮结束不完成任务，不阻塞输入

| 结论 | 证据 |
| --- | --- |
| 通过（API 专项，真实） | `T-20260930-FD4793` 第二轮 `POST …/session/{sid}/message` → `204`，Session ID 始终 `ses_f0d2f9f14ffemfWDJO31Jv41xe`，任务保持 `RUNNING`；真实回复「第二轮完成」 |
| 通过（root 浏览器） | root 记录：第二轮仅一次 `prompt_async=204`（该轮为自然挂起，见 `limits-and-risks.md`）；停止后继续一轮真实成功：UI 3 秒显示「停止后继续正常」，同 Session、Task 仍 `RUNNING` |

## 3 原生问题权限可回答，停止回复后继续，失败超时不结束业务任务

| 子项 | 结论 | 证据 |
| --- | --- | --- |
| 原生 permission | 通过（修复后，见 `fixes.md` 第 2 条） | API 专项：`/permission/{id}/reply` 两次 200；`/session/{sid}/permissions/{id}` 200 且 pending 归 0，模型真实确认输出 |
| 原生 permission（浏览器） | 通过 | root 记录：重开 73AB4C 同 Session，点「允许一次」后 `printf ASTRA_PERMISSION_OK` 正常运行，无错误 toast，权限卡消失 |
| 原生 question | 通过 | API 专项：真实提问 `que_0f2d3eb0…` → `answers:[["否，先不提交"]]` → 200，pending 归 0，模型回复「用户选择「否，先不提交」」；root 浏览器绿色选项闭环同样通过 |
| 停止回复后继续 | 通过（双通道） | API 专项：真实 `abort` 后任务 `WAITING` 非终态、Session 不变，随后新输入真实回复「中断后可继续」；root 浏览器同样通过 |
| 真实失败不结束任务 | 通过 | `T-20260930-4F6969`：真实 Serve 启动失败（外部进程占用 17315）→ `runtime_error` 为真实 `端口冲突：127.0.0.1:17315 被其他进程占用`，任务保持 `PENDING`、无 Session、员工 `current_task_count` 归 0；释放端口后人工继续 → 真实 Session + 真实模型回复 |
| 真实 elapsed 超时 | 通过 | 隔离注入（`evidence/real-verify-20260930/opt-in-timeout-ack/`）：真实 1.2.27 + 真实模型，`ASTRA_OPENCODE_TIMEOUT_SECONDS=12`、control 5s，`time.monotonic()` 实测第 4.018s 起 `RUNNING`、第 16.866s 变为 `WAITING` 且 Session `INTERRUPTED`、`terminal_reason=timeout`，`session_id` 未变、`pending_message_id=null`、连接 `CONNECTED` → **业务任务未被超时结束**；该 prompt 的上游用户消息恰好 1 条（无重复提交）；`stop` 0.085s、再次发送 0.263s 无错误，任务回到 `RUNNING` 且仍是同一 Session |
| 环境不可用不领取 | 通过 | `verify-boot-20260930`（`opencode_path` 指向不存在二进制）环境自检 `UNAVAILABLE`，任务不被领取 |
| in-flight ACK 丢失 / 晚到 ACK | **未验证（真实链路）** | 真实语义仅由模拟回归覆盖（见第 5 项分列）；隔离注入的 `ack-report.json` 为空文件，未产出结果，故不宣称真实通过 |
| 模型/provider 错误注入 | **注入未生效，不作为失败证据** | 先后注入 `opencode/astra-nonexistent-verify-model`、`astra-verify-nonexistent-provider/model-x`，原生实际仍运行 Space Bunny Free 并成功回复（`finish=stop`，有 token），未触发 Session 执行 error；不断言原生 fallback，也不扩展模型架构 |

## 4 工作区读取项目配置，worktree 校验一致，提交后累计 Diff 可见

| 子项 | 结论 | 证据 |
| --- | --- | --- |
| 项目配置继承 | 通过 | 隔离项目根 `opencode.json`（`permission.bash=ask`）被继承到任务 worktree，且真实触发原生 bash 权限请求 |
| 真实提交与累计 Diff | 通过（任务页读取） | `T-20260930-FD4793`：模型真实 `git commit`（`9189d6a`）。任务 Workspace API `GET …/vcs/diff?mode=task` → `['api-verify-2.txt','api-verify.txt']`；`mode=git` → 仅 `['api-verify-2.txt']`；root 真实 Chrome 复核一致：累计双文件并展开提交正文 `+API_VERIFY_OK`，未提交仅 `api-verify-2.txt`（`+API_VERIFY_2_OK`），切回累计正常，无 Loading / 无超时 |
| 原生按 Session 的 Diff | 通过 | `T-20260930-348865` 显式重启后：旧 `ses_f0d203ad3ffeoOPnRcLtWJEHyG` → 原生 `GET /session/{old}/diff` = `['hist-a.txt']`；当前 `ses_f0ceb24dfffeptJCgetbYF4Vhe` → `['hist-b.txt']`。即原生按 Session 隔离，Astra 的 `vcs/diff?mode=task` 是**任务级累计**（跨 Session 共用任务基线），两者是不同视图，不是同一契约 |
| 历史绑定只读与不混 | 通过 | 旧 Session `superseded_by` 指向新 Session；旧消息 12 条且 `sessionID` 集合仅旧值、不含 `hist-b`，新 Session 消息 8 条仅新值；旧 Session 三种写入（`prompt_async`、legacy `session/{id}/permissions/{id}`、`permission/{id}/reply`）均 403，读取 200 |
| 终态 Session 读取 | 通过 | 已 `SUCCEEDED` 的 `T-20260930-FD4793` 仍可按其 Session 读累计 Diff（2 文件）；已 `CANCELED` 的 `T-20260930-52CBF9` 读 Diff 200 `[]`（该任务本无文件改动） |
| 远程（公司 SSH） | **未验证** | 本机无公司 SSH 配置；远程 worktree 校验仅有以命令文本为输入的既有回归，未做真实远程实测 |

## 5 断线重连不丢 Session 不重复提交，晚到 ACK 不覆盖旧轮

| 子项 | 结论 | 证据 |
| --- | --- | --- |
| 真实断线重连 | 通过（真实，但为响应完成后的 Server 断线） | `T-20260930-FD4793` 第六轮响应**已完成之后** `kill -9` 真实 OpenCode Server（17312）→ 任务保留、Astra 记录 `peer closed connection without sending complete message body`；`POST /reconnect` 后真实 Server 重启、Session 仍为 `ses_f0d2f9f14ffemfWDJO31Jv41xe`，该轮真实回复「断线前」只出现一次，用户消息共 7 条无重复。**因此只能称"真实 Server 断线 / reconnect 同 Session / 单一用户消息"** |
| 晚到 ACK / 旧轮隔离 | 通过（模拟，与真实断线分列） | 回归：`test_delayed_ack_does_not_reopen_succeeded_task`、`test_delayed_ack_does_not_clear_manual_confirmation`、`test_lost_ack_is_reconciled_without_duplicate_prompt`、`test_stop_cancels_continued_round_after_lost_ack_on_succeeded_task`、`test_send_does_not_abort_when_background_refresh_acks_first`、`test_previous_completed_turn_cannot_complete_new_submission`、`test_start_lost_ack_preserves_recovery_and_refresh_converges`；真实 in-flight ACK 未验证（见第 3 项） |
| 启动失败后重试复用 | 通过（模拟 + 真实） | 回归 `test_claimed_task_without_session_is_offered_again_for_start_retry`；真实对应 `T-20260930-4F6969` 人工继续 |

## 6 人工完成 / 终止后终态稳定，三界面一致

| 终态 | 结论 | 证据 |
| --- | --- | --- |
| 人工完成 | 通过 | `T-20260930-FD4793` `confirm` → `SUCCEEDED 已完成`；重复 confirm 200 且仍 `SUCCEEDED`；多次 refresh 稳定。任务详情 / 任务列表 / 数字办公室 `dashboard/tasks`（`completed_today=1`，recent 显示「任务已人工确认完成」）/ `dashboard/employees`（员工回到 `IDLE 空闲`，`current_task=null`）/ 员工详情（`today_completed=1`、`completed_sessions=1`）一致 |
| 人工终止 | 通过 | `T-20260930-52CBF9` `POST /stop` → `CANCELED 已取消`；详情 / 列表 / `dashboard/tasks` / 办公室（员工 `IDLE`，`current_task=null`）一致；延迟后仍 `CANCELED`，未重开 |
| 人工终止（浏览器） | 通过 | root 记录：`T-20260930-EE0439`（在 IAB 内创建并手动分配 `verify-20260930`，自动启动、无手动 start；终态核对在其 Chrome 标签完成）真实模型回复「终止验收启动正常」，Task `RUNNING`、完成/终止按钮可用；root 仅点击一次「终止任务」→ 立即 `CANCELED`，reload 仍 `CANCELED`、同 Session `ses_f0cef5117ffeVYPAyWH0V3SBXd`、回复保留。只读核对：`.astra/logs/backend.log` 中该任务仅一条 `POST /stop → 200`，无 start/confirm/restart |
| 浏览器一致性范围 | 部分 | root 已通过：任务详情页与员工详情页；首页（IAB）数字员工卡片「验收员工20260930 空闲 暂无当前任务」与最近任务（EE0439 已取消、73AB4C 已完成）已核对。**传统办公室场景在本分支未挂载**（真实 router 与 Dashboard 均无该路由与切换入口），因此其浏览器一致性未验证，见 `limits-and-risks.md` |
| 终态拒写 | 通过（回归） | `test_native_permission_reply_is_denied_after_business_terminal[SUCCEEDED/CANCELED]`、`test_bound_historical_session_rejects_native_writes`（含 legacy permission POST → 403「历史 Session 只读」，并对照当前 Session 同一操作非 403） |

## 浏览器覆盖范围

root 的真实 Chrome 记录已覆盖：自动启动（手动分配、无手动 start）、首轮正常回复、第二轮输入、
question 绿色闭环、permission「允许一次」闭环、停止后继续、Diff 累计与未提交（最终 controller 版
复核无 Loading / 无超时）、人工完成（`73AB4C`）、人工终止（`EE0439`）、首页与员工详情一致性。
Diff 终态复核在 root 的 Chrome 标签完成，创建与自动启动发生在 IAB 内；两者按实际记录标注，
不合并为同一种浏览器环境。
root 的浏览器截图保存在其会话，未复制为本地文件，故不声称本地截图证据。

## 本轮自建任务的清理

验收结束后对自建且不再使用的任务执行真实 `POST /stop`（保留数据，未删除）：
`T-20260930-348865`、`T-20260930-991887`、`T-20260930-4F6969` 均 `CANCELED 已取消`；
`verify-api-20260930` / `verify-fail-20260930` / `verify-port-20260930` 回到 `IDLE`、
`current_task_count=0`。`T-20260930-FD4793`（root 只读复用的 Diff fixture）保持 `SUCCEEDED`；
`T-20260930-66442B`、`T-20260930-52CBF9` 此前已 `CANCELED`。root 的 `73AB4C` / `EE0439`
与 `verify-20260930` 未做任何写入。

`frontend/e2e/task-diff-race.spec.ts` 需要一个真实任务作为入口，通过环境变量
`ASTRA_DIFF_RACE_TASK` 传入；未设置时整组跳过，不影响常规 E2E。
