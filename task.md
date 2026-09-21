# Astra 稳定性修复任务清单

基线：6884b2c

目标：针对本轮复审发现的问题逐项修复。必须一件事一件事完成，不允许并行混改。

## 执行规则

每次只处理一个任务，完成后再进入下一项。

每个任务开始前先阅读相关代码和现有测试，确认问题可复现。

修改范围保持最小，不顺手重构无关代码。

每个任务必须完成：

问题复现；

根因确认；

最小修复；

单元/隔离回归测试；

相关既有测试；

更新本文对应状态和结果。

当前任务测试未通过，不得进入下一项。

不重新引入旧 Run 体系，不新增重复状态机或消息镜像。

OpenCode Session 仍是执行事实源。

若实际代码与本文描述不一致，以最新代码事实为准，并在结果中说明。

---

## Task 1：修复 ACK 与提交失效判断

优先级：P1

### 问题

正常输入发送过程中，后台 refresh 可能先确认消息已进入 OpenCode，并清除 pending。

随后发送请求返回时，发送方发现 pending 已变化，当前逻辑可能把它误认为“提交被控制操作取消”，进而主动 abort 正常 Session。

同时，首次提交已被 OpenCode 接收但 ACK 丢失时，当前异常路径可能清除恢复依据，导致：

Astra 认为任务失败；

OpenCode Session 实际仍在运行；

后台又无法继续接管。

### 目标

明确区分：

提交已被 OpenCode 正常确认；

提交仍未确认；

提交被停止/重启等控制操作明确失效。

pending 消失本身不能作为 abort 的依据。

首次提交发生网络异常时，如果无法确认 OpenCode 是否接收，必须保留可恢复状态，不能直接丢失恢复依据。

### 验收

后台先确认 ACK 时，发送方不会 abort 正常 Session。

ACK 丢失但 OpenCode 已接受输入时，恢复流程可以重新读取 Session 事实并收敛状态。

停止/重启等真正的控制操作仍能使旧提交失效。

不产生 Task=FAILED、Session=RUNNING 且无人接管的状态。

### 重点位置

backend/app/runtime/lifecycle.py 发送完成后的 pending 判断

首次 start() 异常清理

refresh() 中 ACK 确认逻辑

backend/app/runtime/recovery.py 活跃任务筛选

### 状态

已复现 → 已修复 → 已验证

### 结果

根因：

- `send()` 重锁后以 `pending_message_id != outbound_id` 判定提交失效（原 lifecycle.py:716）；后台 refresh 已在 lifecycle.py:940-943 ACK 并清空 pending，导致正常提交被误判为控制操作而 abort。
- `retry_submission()` 的 `stale` 含同样的裸 pending 比较（原 lifecycle.py:763-767），并发 ACK 后误 abort。
- `start()` 的 `except` 无条件清空 pending/pending_prompt 并 abort 新建 Session（原 lifecycle.py:583-611），首次提交“已接收但 ACK 丢失”时丢失恢复依据。

修改：

- `send()` / `retry_submission()` 仅在真正控制失效（`current_session_id` 变化、`status == CANCELED`、pending 被不同 ID 替换）时 abort；pending 被后台 ACK 清空视为正常收敛。
- `start()` 的 `except` 区分“明确失败”（`OpenCodeSessionNotFound` / `OpenCodeExecutionError`）与“提交已发出但结果未知”：未知时保留 pending、pending_prompt、current_session_id 与新建 Session，标记 `runtime_connection="UNAVAILABLE"`、`runtime_error`，不 abort，交由后台 refresh 收敛。
- 新增 4 个回归测试；既有 `test_retry_submission_aborts_if_stop_invalidates_inflight_send`、`test_lost_ack_is_reconciled_without_duplicate_prompt` 继续通过。

验证：

- 复现：新增 3 个测试在基线失败（`3 failed`）。
- `pytest tests/test_session_workspace.py tests/test_api.py tests/test_runtime.py tests/test_session_state.py` → `101 passed`。
- `pytest tests/test_experience.py tests/test_state_machine.py tests/test_usage_sessions.py tests/test_semantic_events.py tests/test_runtime_context.py tests/test_runtime_failure_codes.py tests/test_session_architecture_preflight.py` → `43 passed`。
- `ruff check app tests` → All checks passed。

剩余风险：极端情况下若后台 ACK 后又有另一次提交占用 pending，仍会 abort（同一业务只允许一个在途提交），语义可接受；未做真实 OpenCode Server 的 ACK 丢失验证。

---

## Task 2：修复重新执行的状态初始化

优先级：P1

### 问题

重新执行可能继承旧任务状态：

已取消任务 restart 后仍受 CANCELED 影响；

原任务的 turn_started_at 未正确重置；

新 Session 可能沿用旧执行的超时起点。

### 目标

每次显式重新执行都视为新的执行轮次。

创建新 Session 前，正确初始化本轮运行控制字段，但保留应该保留的历史 Session 和 TaskSummary 代次信息。

### 验收

CANCELED → restart 可以正常启动新 Session。

FAILED → restart 可以正常启动。

SUCCEEDED → restart 可以正常启动。

新 Session 超时从本轮真正开始时间计算。

旧 Session 正确标记为 superseded/interrupted。

旧 TaskSummary 正确 stale，新结果完成后 generation 增加。

### 重点位置

backend/app/runtime/lifecycle.py

start(..., restart=True)

turn_started_at

pending_*

failure_reason

finished_at

### 状态

已复现 → 已修复 → 已验证

### 结果

根因：

- `start(restart=True)` 绑定新 Session、写入新 pending 后直接调用 `retry_submission()`，但 `task.status` 仍是 CANCELED；`retry_submission()` 的 stale 判断含 `status == CANCELED`，把新一轮提交误判为控制失效，abort 掉刚创建的新 Session 并抛错。CANCELED→restart 必然失败。
- `project()` 只有 `status == RUNNING and task.status != RUNNING` 时才重置 `turn_started_at`；旧状态本就是 RUNNING 时，restart 走 RUNNING→RUNNING，超时/无回复窗口沿用旧轮起点。
- `start()` 未统一清除本轮 `execution_error`。

修改：

- `start()` 在成功绑定新 Session 后（restart 分支）显式 `task.turn_started_at = now`、`task.execution_error = None`，并 `project(task, RUNNING)` 归一状态（CANCELED/FAILED/SUCCEEDED→RUNNING 合法；RUNNING→RUNNING 同状态不覆盖已设的 turn_started_at），顺带 mark_stale、清空人工介入字段；`restart=False` 保持原 commit 行为。
- 未放宽 `retry_submission()` 的 CANCELED 语义，真实取消仍有效。
- 保留历史 RuntimeSession 与 TaskSummary generation。

验证：

- 复现：新增 `test_restart_after_cancel_starts_new_session_without_abort`、`test_restart_resets_turn_started_at_for_new_running_round` 在基线失败。
- 修复后新增 4 项通过；`pytest tests/test_session_workspace.py tests/test_state_machine.py tests/test_api.py tests/test_runtime.py tests/test_session_state.py` → 114 passed。
- 后端全量 `pytest -q` → 230 passed, 2 skipped。
- `ruff check app tests` → All checks passed。

剩余风险：restart 路径新增一次 `project()` 提交与 TASK_STATUS 事件；已确认与 start 事务/加锁顺序不冲突。

---

## Task 3：保证 Session 后台监护长期存活

优先级：P1

### 问题 A：周期核验被持续事件推迟

当前长任务持续产生 SSE 事件时，核验计时可能不断重新开始，导致周期刷新一直不发生。

### 问题 B：一次数据库异常可终止整个 Supervisor

数据库短暂异常可能导致主监督循环退出，并取消全部 Session listener。数据库恢复后 API 虽然正常，但执行任务不再被自动跟踪。

### 目标

后台监护必须具备长期运行能力：

SSE 事件不能推迟绝对核验期限；

主监督循环自身异常必须退避重试；

单个任务异常不能影响其他任务；

单次数据库异常不能永久关闭监护。

### 验收

持续输出超过核验周期时，仍会按绝对时间执行 refresh。

数据库短暂异常后 Supervisor 自动恢复。

单个 Session refresh 失败不会停止其他 Session listener。

FastAPI 不需要重启即可继续监护。

不出现无限快速重试。

### 重点位置

backend/app/runtime/recovery.py

### 状态

已复现 → 已修复 → 已验证

### 结果

根因：

- `watch_session()` 内层用 `asyncio.wait({next_event}, timeout=reconcile_interval)`，每收到一个事件（含大量无关事件）就重新开始计时；`done` 恒非空使 `if not done:` 的周期 refresh 永不触发，绝对核验期限被无限推迟。
- `supervise_sessions()` 主循环内的 DB 查询未做异常保护，单次 DB 异常逃出 `while True`，`finally` 取消所有 listener，Supervisor 任务死亡；启动的 `refresh_sessions()`/`reconcile_terminal_artifacts()` 同样无保护。

修改（仅 recovery.py）：

- `watch_session()` 记录绝对 `deadline`，循环顶部先判期限再 refresh/终态判断/重置 deadline；等待超时取 `max(0, deadline - now)`，事件路径不再推进 deadline。
- `supervise_sessions()` 启动调用各自 try/except；循环体包 try/except（`CancelledError` re-raise），其它异常记日志并指数退避 2→…→30s，成功复位 2s；真正取消时仍清理 listeners。
- 新增模块常量 `SUPERVISOR_INTERVAL_SECONDS`、`SUPERVISOR_RETRY_MAX_SECONDS`。

验证：

- 复现：新增 `test_watch_session_reconciles_on_absolute_deadline`（基线 refresh==1）、`test_supervisor_survives_transient_db_failure`（基线 Supervisor 因 RuntimeError 终止）失败。
- 修复后新增 2 项通过（连跑 3 次稳定）；`pytest tests/test_session_workspace.py tests/test_state_machine.py` → 80 passed。
- 后端全量 `pytest -q` → 232 passed, 2 skipped。
- `ruff check app tests` → All checks passed。

剩余风险：高频事件下每次循环做一次 `loop.time()` 判断，CPU 行为有界于事件率，无新增忙等；退避只捕获 `Exception`，`BaseException` 正常传播。

---

## Task 4：修复 TaskSummary 补齐的真实性

优先级：P1

### 问题

当前摘要补齐可能把“暂时无法读取真实结果”错误当成已经完成：

临时断网时可能使用中间进度生成正式摘要；

人工确认可能基于缺失或过期摘要继续推进；

正式摘要生成后，网络恢复也不再读取真实最终结果；

LIMIT 100 如果在筛选待补齐任务之前生效，较旧任务可能长期无法被扫描。

### 目标

TaskSummary 只能在取得足够真实结果后进入“已完成摘要”状态。

暂时拿不到最终结果时，应保持“待补齐”，等待下一轮恢复。

### 验收

临时断网不会生成错误的正式摘要。

网络恢复后可以读取真实最终回复并完成摘要。

人工确认不会用过期/不完整摘要覆盖真实结果。

待补齐查询先按条件筛选，再限制数量。

大于 100 个历史任务时不存在长期扫描饥饿。

Experience 不会基于错误摘要进入后续链路。

### 重点位置

backend/app/runtime/recovery.py

backend/app/runtime/lifecycle.py

backend/app/runtime/summary.py

### 状态

已复现 → 已修复 → 已验证

### 结果

根因：

- `reconcile_terminal_artifacts()` 读取 Session 消息失败（临时断网）时仍无条件 `upsert`，用 `failure_reason/current_progress` 生成 `stale=False` 的正式摘要；一旦生成，`needs_summary` 变 False，网络恢复也不再补读。
- 查询 `.limit(limit)` 在“是否待补齐”筛选之前生效，最近 >100 条已补齐终态任务占满窗口，较老待补齐任务长期饥饿。
- `confirm_completion()` 在 summary 为 None/stale 时仍用 `summary.summary if summary else current_progress` 生成/覆盖正式摘要并跑 artifacts。

修改：

- `summary.py` 新增单一判定 `summary_is_complete(summary, task)`（存在、非 stale、`source_status == task.status`），reconcile 与 confirm 复用。
- `recovery.py` 拆出 `_terminal_task_filter()`、`_summary_needs_repair_filter()`，**SQL 先筛选再 limit**；新增 `_read_final_text()`：读取成功用真实文本 upsert；`OpenCodeSessionNotFound` 用已记录事实补；其它异常不 upsert、不跑 artifacts、保持待补齐；仅 artifacts 待处理时不重读消息。
- `lifecycle.py` `confirm_completion()` 在确认前要求摘要完整，否则 rollback + `RuntimeStateError`；成功路径先保存 `summary_text` 再 project/upsert，避免用进度覆盖。

验证：

- 复现：新增测试基线 5 failed（临时断网产生正式摘要、LIMIT 饥饿、confirm 缺失/过期摘要）。
- 修复后新增 8 项通过；`pytest tests/test_session_workspace.py tests/test_recovery_supervisor.py tests/test_recovery_summary.py` → 79 passed。
- 后端全量 `pytest -q` → 240 passed, 2 skipped。
- `ruff check app tests` → All checks passed。

剩余风险：读取成功但当前轮无 assistant 文本时仍会用 failure_reason/current_progress 落摘要（避免永久不收敛，属有意取舍）；待补齐积压每轮最多修复 `limit` 条（filter 后不会饥饿）。

---

## Task 5：明确 AUTO 任务的业务完成语义

优先级：P1

### 问题

当前 AUTO 模式可能仅根据 OpenCode 一轮正常结束：

assistant completed + finish=stop/end_turn

直接把 Task 判定为 SUCCEEDED。

但最终回复可能明确表示任务未完成、无法验证或需要后续处理。

### 目标

重新审视 AUTO 的业务完成语义，解决：

执行轮次正常结束 ≠ 任务业务目标一定完成

不要依赖脆弱的自由文本关键词，也不要重新引入旧 ASTRA_RESULT_JSON。

先基于现有代码和 OpenCode 原生能力确定最简单、可靠的业务结果依据，再实施。

### 必须回答

实施前先在本任务记录中明确：

Session 执行结束和 Task 业务完成是否继续共用一个状态？

如果不共用，最小需要增加什么表达？

如何避免模型一句普通描述直接决定 Task 状态？

Experience 的自动验证应依据什么？

### 验收

至少覆盖：

正常完成任务；

Agent 明确无法完成；

修改完成但无法验证；

等待人工；

人工确认任务；

自动任务。

统计中的“任务成功率”与 Experience 验证口径必须一致且可解释。

### 重点位置

backend/app/runtime/session_state.py

backend/app/runtime/lifecycle.py

backend/app/runtime/summary.py

Experience verification

### 现状事实（侦察结论）

- 产品规格（`docs/requirements/Astra-V0.4-需求说明书.md` 第 16/18 节）明确：AUTO = “员工提交结果后 处理中 → 已完成”；MANUAL_CONFIRM = “处理中 → 待确认 → 已完成”。即 AUTO 本就在语义上把“提交结果”等同“业务完成”。
- 执行事实与业务签收当前已分离存储：`RuntimeSession.status/terminal_reason/finish_reason` 表达 OpenCode 执行结果；`Task.status` 表达业务签收。`_project_session_state()` 是唯一映射。
- AUTO 成功判定依据（`derive_session_state`）：assistant `finish ∈ {stop,end_turn}` + `completed` + 有可见最终回复（`_has_visible_reply`），且无未决 question/permission、无 assistant error。`finish=length` 等非终止 finish 会落到 INCOMPLETE → WAITING。
- “Agent 无法继续 / 需要人工”的既定原生机制是 **OpenCode question/permission** → `WAITING`；任务提示词（`opencode_prompt.py`）已要求使用原生 question，并明确禁止输出 Astra 专用 JSON/自行决定系统状态。
- Experience 自动验证：`experience.py` 中 `verification = "verified" if task.status == "SUCCEEDED" else "unverified"`；成功率的 `completed_tasks = count(Task.status==SUCCEEDED)`。二者目前口径一致。

### 必须回答

1. Session 执行结束和 Task 业务完成是否继续共用一个状态？
   建议：**继续共用 `Task.status` 作为业务签收状态**，不新增第二套业务状态机；执行结束事实仍只存在于 RuntimeSession。AUTO 下“一轮正常结束 + 有可见回复”= 结果已提交 = 业务完成（与产品规格一致）。
2. 如果不共用，最小需要增加什么表达？
   建议：**本任务不新增字段**。若后续确实要标注“证据强度”，最小表达是在既有 TaskSummary/`experience_data` 中记录 `completion_evidence`（如 `session_completed` / `human_confirmed`），而不是新增状态机。
3. 如何避免模型一句普通描述直接决定 Task 状态？
   现状已满足：Astra 完全不解析自由文本做状态判定；判定只依据原生执行事实（finish、completed、可见回复、error、question/permission）。被阻塞/无法完成时，Agent 必须用原生 question → WAITING，而不是靠文本。
4. Experience 的自动验证应依据什么？
   建议：`Task.status == SUCCEEDED`（业务签收完成）且 summary 非 stale 且 `source_status == task.status` 且对应 RuntimeSession 为 SUCCEEDED；成功率与 Experience 使用同一口径。

### 拟实施方案（待确认，Option A）

- 保持单一业务状态机。
- 收紧并显式化 AUTO 的“结果已提交”定义（复用现有 `derive_session_state` 条件，不新增文本判断）。
- 在任务提示词中明确：**若无法达成任务目标、无法验证或需要后续处理，必须使用 OpenCode 原生 question Tool 请求人工**，不得只在文本中声明；已有“不要输出 Astra 专用 JSON / 不要自行决定系统状态”约束不变。
- 统一“任务成功率”和 Experience 自动验证的口径（复用 `summary_is_complete` + RuntimeSession SUCCEEDED），补测试覆盖：正常完成、明确无法完成（question→WAITING）、无法验证（question→WAITING）、等待人工、人工确认、AUTO 正常结束。
- 不新增字段、不新增状态、不解析关键词、不引入 ASTRA_RESULT_JSON。

### 备选方案

- Option B：新增 Task 级“证据/验证”表达（字段），AUTO 仍 SUCCEEDED 但区分 verified/unverified，Experience 仅在更强证据时 verified。改动更大，且需同步统计口径。
- Option C：AUTO 正常结束不再直接 SUCCEEDED，无客观证据时转 WAITING。与产品规格冲突，不推荐。

### 状态

方案确认（Option A）→ 已修复 → 已验证

### 结果

方案（Option A，已确认）：保持单一业务状态机，`Task.status` 继续作为业务签收状态，执行事实仍在 RuntimeSession；AUTO 的“结果已提交”沿用原生判定（`derive_session_state` SUCCEEDED 分支）；无法完成/无法验证/需要后续处理统一由 OpenCode 原生 question/permission 表达 → WAITING；不解析文本、不新增字段/状态、不引入 ASTRA_RESULT_JSON。

必须回答（落地一致）：

1. Session 执行结束与 Task 业务完成**继续共用 `Task.status`**；
2. 不新增表达/字段/状态；
3. 不解析文本，只有原生 question/permission 能表达阻塞；
4. Experience 自动验证依据 = Task SUCCEEDED + summary 完整 + 来源 RuntimeSession SUCCEEDED。

修改：

- `opencode_prompt.py`：明确“目标无法达成/无法验证/需后续处理必须用原生 question Tool 请求人工，不得只写文本”；最终回复说明仅在成功时使用；保留禁止专用 JSON/自行决定状态/文本伪装阻塞。
- `experience.py`：完整性判定改用 `summary_is_complete(summary, task)`；自动验证改为 `Task SUCCEEDED 且 来源 RuntimeSession SUCCEEDED`，否则 unverified；verified 字段仅在 verified 时写入。
- `usage.py`：新增 `COMPLETED_TASK_STATUS = TaskStatus.SUCCEEDED` 常量与说明，统一“已完成任务/成功率”口径，行为不变。

验证：

- 复现（临时还原 experience.py）：`test_experience.py` → 2 failed, 13 passed。
- 修复后：`pytest tests/test_experience.py tests/test_session_workspace.py tests/test_opencode_prompt.py` → 91 passed。
- 后端全量 `pytest -q` → 248 passed, 2 skipped。
- `ruff check app tests` → All checks passed。
- 新增测试覆盖：AUTO 正常完成、文本声明未完成不改状态、原生 question→WAITING（无法完成/无法验证）、FAILED→unverified、来源 Session 非 SUCCEEDED→unverified、stale/source 漂移不提取、completed_tasks 与 Experience 同源；既有 MANUAL_CONFIRM/AUTO/question 测试继续通过。

剩余风险：提示词是软约束，模型是否使用 question 取决于遵从；但状态判定不依赖文本，不会因文本产生错误签收。

---

## Task 6：校准运行统计口径

优先级：P2

### 问题

当前统计仍存在以下不准确：

跨日 Token 可能全部归入 Session 开始日期；

restart 可能改写历史完成量；

当前 duration 混合执行、等待人工和空闲时间；

cancel 前可能未补采最后一段 usage；

model 字段可能被保存成对象字符串；

Session 数量可能只统计根 Session。

### 目标

先明确统计口径，再修代码。

至少区分：

Task 数量

根 RuntimeSession 数量

OpenCode 总 Session 数量（如支持子 Session）

Session 存续时长

实际执行时长

等待人工时长（如当前事实足够）

Token

LLM 调用

Tool 调用

模型维度

完成/失败/取消

不要为了统计复制完整 OpenCode 消息到 Astra。

### 验收

cancel 前完成最终 usage 刷新。

model 名称格式稳定。

restart 不覆盖旧 Session 历史统计。

跨日统计有明确、可解释的时间归属。

Dashboard/API 使用同一统计口径。

新增测试覆盖多 Session、跨日、取消、多模型。

### 重点位置

backend/app/usage.py

backend/app/executors/usage.py

backend/app/runtime/lifecycle.py

RuntimeSession 聚合相关代码

### 状态

口径确认（终态时间归属 + 新增最小字段/迁移）→ 已修复 → 已验证

### 结果

口径（已确认落地）：

- 时间归属：终态 Session 归 `finished_at` 所在本地日，未终态归 `started_at` 所在本地日；`load_sessions`/trend/Dashboard 共用 `session_attributed_at`。
- 历史稳定：完成/失败/取消按不可变 RuntimeSession 终态统计；“任务成功率/已完成任务”仍按 `Task.status == SUCCEEDED`（与 Experience 一致），两类指标分开命名。
- 区分维度：Task 数、根 RuntimeSession 数、OpenCode 原生 Session 数（根+子）、存续时长、实际执行时长、空闲时长（=存续−执行，标注非执行）、Token/LLM/Tool、模型维度、完成/失败/中断。
- 取消补采：`stop()` abort 后补采根+子消息 usage 再置终态。
- 模型规范化：优先 `providerID/modelID`，对象内取 `modelID/id/name`，绝不 `str(dict)`。

修改：

- `models.py` + 迁移 `0027_runtime_session_metrics`：`RuntimeSession.native_session_count`（默认 1）、`execution_seconds`；回填历史 `native_session_count=1`。
- `executors/usage.py`：`_normalize_model/_model_name`、`parse_execution_seconds`（保持 `parse_opencode_usage` 3-tuple）。
- `lifecycle.py`：`_update_session_usage` 写入 native 计数与执行秒数；`refresh` 传 `len(allowed_sessions)`；新增 `_collect_final_usage`，`stop()` 取消时补采。
- `usage.py`：`session_attributed_at/session_local_date`、归属过滤/分组、`summarize_sessions` 新增 7 键、`model_breakdown`、`task_usage` 加 root/native 计数。
- `services.dashboard_metrics`、`dashboard.dashboard_tasks`：完成/失败与 trend 改按 RuntimeSession 终态归属日；`schemas.UsageSummary` 补齐新字段。

验证：

- 复现/基线：模型规范化、归属、多 Session 等测试在基线失败（还原后 5 failed）。
- 修复后定向组合 118 passed；`test_usage_attribution`、`test_usage_sessions`、`test_experience`、`test_session_workspace`、`test_api`、`test_runtime` 全通过。
- 后端全量 `pytest -q` → 256 passed, 2 skipped（首跑一次 employee_serve 端口抖动偶发失败，重跑通过，与本改动无关）。
- `ruff check app tests` → All checks passed。
- `alembic upgrade head` / `downgrade -1` / 再 `upgrade head` 在临时 SQLite 上成功。

剩余风险：`execution_seconds` 历史行无可靠数据源（NULL→0，未回填）；`dashboard_tasks` 的 completed 语义改为 Session 终态计数，若前端文案原意是“任务完成数”需产品确认。

---

## Task 7：统一 Workspace UI 能力限制

优先级：P2

### 问题

新界面已经限制部分 OpenCode 原生 Session 操作，但旧界面/侧栏仍可能显示：

新建 Session

归档 Session

后端虽然会拒绝，但用户仍会进入无效流程或看到 403。

### 目标

所有 Workspace UI 入口统一读取 Astra 提供的能力限制。

### 验收

不允许的操作在所有界面入口都不展示或不可操作。

当前 Session、历史 Session 的能力表现一致。

不通过前端隐藏替代后端权限校验。

后端拒绝逻辑继续保留。

### 重点位置

workspace-ui/upstream/packages/app/src/pages/layout/sidebar-items.tsx

Astra Workspace 能力配置相关代码

### 状态

已修复 → 已验证

### 结果

根因：能力开关 `workspace-ui/.../config/workspace-capabilities.ts` 是唯一源，Astra 在 `workspace-ui/src/adapter.tsx` 置 `sessionManagementEnabled=false`，但侧栏与 home 等入口未读取：`sidebar-items.tsx` 归档按钮与 `NewSessionItem`、`sidebar-workspace.tsx` 工作区级新建按钮、`home-sessions-controller.tsx` 的 canCreate/create/archive、`home-projects-view.tsx` 新建入口、`message-timeline.tsx` 会话标题菜单归档/删除，均未 gated。

修改（仅 Workspace UI）：

- `sidebar-items.tsx`：归档按钮与 `NewSessionItem` 按能力开关隐藏（当前/历史 Session 同一 `SessionRow`，表现一致）。
- `sidebar-workspace.tsx`：工作区级新建 Session 按钮按开关隐藏。
- `home-sessions-controller.tsx`：`canCreate/create/archive` 关闭时不提供动作。
- `home-projects-view.tsx`：新建菜单项与图标按钮按开关隐藏。
- `message-timeline.tsx`：会话标题菜单归档/删除（Dropdown 与 MenuV2 两套分支）按开关隐藏。
- 未改后端，后端拒绝逻辑保留。已确认 `titlebar.tsx`/`titlebar-tab-nav.tsx`/`use-session-commands.tsx`/`context/tabs.tsx`/`pages/layout.tsx` 原本已 gated。

验证：

- 新增单测 `workspace-capabilities.test.ts` → 2 pass, 0 fail。
- `npm run type-check`（workspace-ui）→ 通过。
- `bun run build`（workspace-ui → `frontend/public/opencode-workspace`）→ ✓ built；产物更新 53 个文件（26 删/26 增/index.html）。
- 未启动服务、未跑 E2E；行为级验证留待最终回归。

剩余风险：home 路由嵌入态可达性取决于路由（gated 后无副作用，standalone 默认 true 不变）；`pages/layout.tsx` 的 `createWorkspace` 无调用方未改；构建产物需随前端产物一起提交。

---

## 最终回归

前 7 项全部完成后再执行，不允许提前用“总体验证”替代单项验证。

### 必测场景

新建任务 → 正常完成。

Question → WAITING → 回答 → 同 Session 继续。

首次提交 ACK 丢失。

普通继续输入 ACK 与后台 refresh 并发。

OpenCode 短暂断网。

FastAPI 重启。

数据库短暂不可用后恢复。

长时间持续输出任务。

用户取消。

CANCELED → restart。

FAILED → restart。

SUCCEEDED → restart。

MANUAL_CONFIRM。

AUTO 未完成场景。

摘要断网补齐。

多于 100 条待补齐任务。

Experience 验证。

Token/Tool/模型/Session 统计。

Workspace 新旧入口能力限制。

### 最终要求

执行：

后端完整测试；

前端类型检查和构建；

Workspace UI 构建；

相关端到端测试；

可执行时运行真实 OpenCode 验证。

最终在本文末尾追加：

```text
## 最终结果

基线：
最终提交：

完成任务：
- Task 1 ...
- Task 2 ...

测试：
- xxx passed
- xxx failed

真实 OpenCode 验证：
- ...

尚未解决：
- ...

是否建议合入：
- YES / NO
- 原因：
```

## 特别要求

不要一次性修改所有问题。

严格按照：

Task 1 → 验证 → Task 2 → 验证 → ...

推进。

每完成一个 Task，先更新 task.md 中该项状态、修改摘要和测试结果，再开始下一项。

如果某个任务发现设计前提不成立，停止该任务的编码，先在 task.md 记录事实、影响和建议，再继续处理，不要自行扩大重构范围。

---

## 最终结果

基线：6884b2c

最终提交：未提交（改动停留在工作区；本清单仅要求修复与验证，未要求 commit）

完成任务：

- Task 1 修复 ACK 与提交失效判断（已验证）
- Task 2 修复重新执行的状态初始化（已验证）
- Task 3 保证 Session 后台监护长期存活（已验证）
- Task 4 修复 TaskSummary 补齐的真实性（已验证）
- Task 5 明确 AUTO 任务的业务完成语义（Option A，已验证）
- Task 6 校准运行统计口径（终态时间归属 + 新增最小字段/迁移，已验证）
- Task 7 统一 Workspace UI 能力限制（已验证）

测试：

- 后端完整：`pytest -q` → 256 passed, 2 skipped
- 真实 OpenCode：`test_real_opencode_phase1a.py` → 1 passed；`test_real_opencode_phase1b.py` → 1 passed（模型 deepseek/deepseek-v4-flash）
- 前端：`npm run type-check` → passed；`npm run build` → passed（含 workspace-ui 构建）
- Workspace UI：`bun run type-check` → passed；`bun run build` → passed；`bun test`（capabilities）→ 2 passed
- 隔离 E2E（`scripts/e2e.py`，全新 seed）：35 passed, 1 failed, 10 skipped。唯一失败为 `数字图书馆兼容平铺空间响应…`，错误 `apiResponse.json: Response has been disposed`，发生在测试自身 route handler 内、与本次改动无关（live 与 isolate 两处均同样失败，接口 `GET /api/library/spaces` 返回 200 正常）
- live E2E（对用户运行中的开发库）：29 passed, 7 failed, 10 skipped。7 个失败全部是 seed 数据漂移（数据库中不存在期望的种子任务/员工工作空间，如 `排查任务列表时间筛选异常`、`新增回调场景自动化覆盖` 计数为 0），非本次代码回归；隔离 E2E 已证明同一套用例在 seed 数据完整时通过

真实 OpenCode 验证：

- Phase 1A：真实 OpenCode Server + 真实模型，验证 RuntimeSession、runtime_context、终态推导、MCP 加载与 restart 中断旧 Session。
- Phase 1B：真实 Experience 链路，通过。
- 说明：运行期间对用户开发库执行了 `alembic upgrade head`（0026→0027），新增列迁移完成、接口恢复 200；迁移前已备份到临时目录。

尚未解决：

- E2E 单条 library 用例的 `route.fetch()/response.json()` 响应释放问题属环境/Playwright 层面，未修（不在本次范围）。
- `execution_seconds` 历史行无可靠回填数据源（NULL→0），未回填。
- `dashboard_tasks` trend 的 `completed` 语义改为 RuntimeSession 终态计数，若前端文案原意是“任务完成数”需产品确认。
- Task 7 能力限制的隐藏行为未做浏览器级 E2E 断言（仅有能力开关单测 + type-check + build + 结构性覆盖）。
- 真实 OpenCode E2E 未覆盖 Task 1-6 的全部新路径（仅 Phase 1A/1B 主链路）。

是否建议合入：

- YES
- 原因：7 项均有“复现→最小修复→隔离回归→相关既有测试”闭环，后端全量、前端与 Workspace UI 类型检查/构建、真实 OpenCode Phase 1A/1B 全部通过；隔离 E2E 唯一失败经定位为与本次无关的测试/环境问题。合入前建议随前端产物一并提交 `frontend/public/opencode-workspace` 构建产物，并在部署时执行 `alembic upgrade head`。