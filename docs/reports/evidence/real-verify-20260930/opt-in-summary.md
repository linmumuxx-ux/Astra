# Opt-in 真实环境联调记录（独立执行，2026-09-30）

范围：4 项此前 skip 的 opt-in 联调。全部真实执行，未 mock gateway、未改测试断言使其通过、未提交 Git。
隔离：本机 Redis db15（运行前 `DBSIZE=0`）；隔离 CLI 1.2.27 + 脚本自带 free_port/临时 sqlite；未触碰 db0(Celery)、17311/17312/17313/8100。

## 结果总览

| 项 | 命令要点 | 结果 |
|---|---|---|
| Redis Lua 脚本 | `ASTRA_TEST_REDIS_URL=redis://127.0.0.1:6379/15` | PASSED |
| Redis 吊销集合/哨兵 | 同上 | PASSED |
| Phase1A 真实 Session 关键路径 | `ASTRA_REAL_OPENCODE=1 ASTRA_REAL_OPENCODE_MODEL=opencode/space-bunny-free PHASE1A_OPENCODE=<1.2.27 bin>` | PASSED |
| Phase1B 真实 assistant+MCP 验收 | 同上 + `PATH=<.venv/bin>:<1.2.27 shim>` | PASSED |

原始日志与报告 JSON 位于 `opt-in-redis/`、`opt-in-phase1a/`、`opt-in-phase1b/`，
按 `.gitignore` **仅本地保留、不入 Git**；脱敏结论记录在本文件。

## 0. 真实 elapsed 超时注入（同一隔离方式）

真实 1.2.27 + 真实模型，隔离 fixture（独立临时 SQLite、free_port、`ASTRA_OPENCODE_TIMEOUT_SECONDS=12`、
control 5s），`time.monotonic()` 实测：

| 观测 | 值 |
| --- | --- |
| 第 1 次 `RUNNING` | 单调 4.018s |
| 变为 `WAITING` | 单调 16.866s（Session `INTERRUPTED`、`terminal_reason=timeout`） |
| 超时后 | Session ID 未变、`pending_message_id=null`、`runtime_connection=CONNECTED` |
| 结论 | **超时未结束业务任务**；该 prompt 上游用户消息恰好 1 条（无重复提交） |
| 之后 | `stop` 0.085s、再次发送 0.263s 无错误，任务回到 `RUNNING` 且仍为同一 Session |

原始 `timeout-report.json` / 日志与限定时间序列 README 仅本地保留（被 `.gitignore` 忽略）。

隔离清理已完成：`T-TIMEOUT`、`T-ACK` 均以正常 `RuntimeService.stop(cancel_task=True)` 从 `RUNNING`
转为 `CANCELED`，Session 保持原绑定并标记 `INTERRUPTED` / reason `aborted`；SQLite 行、Session 记录、
worktree 与日志全部保留；relay 50883 与自身 `astra-inject` 进程已关闭（相关端口 0 listener）；
12s/5s 预算只存在于已退出的独立子进程环境，项目 `.env` 与产品配置未改。

**Session execution error（真实轮次失败）未覆盖**：
可用的真实失败只有 Serve 启动失败（端口被占，属任务层启动失败），不能替代 Session 执行期错误。
曾注入不存在的模型与不存在的 provider，**注入未生效**：原生实际仍运行 Space Bunny Free 并成功回复，
因此未触发 Session 执行 error；不断言原生做了 fallback，也不为此扩展模型架构。

## 0.1 真实 ACK 延迟注入（转发器逐请求转发真实 1.2.27）

转发器为本地 stdlib HTTP 代理，**逐请求真实转发到真实 1.2.27**（真实 204 由上游返回，
`GET /global/health`、`/path`、会话与消息读取均为上游真实应答，代理不合成响应）。
注入仅对原生 `prompt_async` 生效：先完整转发并取得真实 204，再把该 ACK 扣住 9s
（超过 `ASTRA_OPENCODE_CONTROL_TIMEOUT_SECONDS=5`），扣满后写回仍打开的连接。

| 事实 | 值 |
| --- | --- |
| A messageID（上游真实 204 携带） | `msg_0f32270d80007917a10a5a68ff` |
| B messageID | `msg_0f322ae9000091c2dbd4ec0939` |
| A 轮控制调用 | `5.68s` 后真实抛 `OpenCodeExecutionTimeout`（ACK 被扣期间），`pending_message_id` = A 的 messageID |
| ACK 释放 | `released=true`、`release_error=null`；**释放早于** refresh 与 B |
| 释放后 refresh | `0.117s`，Task `RUNNING`，**同一 Session** `ses_f0cdd8ccdffeBpryg2gh6gnKLh`，指针恢复到 A 的 messageID，`pending` 清空 |
| B 提交 | `0.127s` 无错误，指针移动到 B 的 messageID，Session 未变 |
| 原生消息唯一性 | 原生用户消息 A、B 各 1 条；真实回复 `ACK_ROUND1_OK` / `ACK_ROUND2_OK` 各 1 条 |
| Task 终态 | 两个检查点均 `RUNNING`（非终态） |

**可称范围（仅此）**：真实 ACK 延迟 → 控制面真实超时 → refresh 在同一 Session 上把指针恢复到
该轮真实 messageID 并清空 `pending` → 新一轮提交成功、原生用户消息 A/B 各 1 条且模型回复各 1 条（不断言 HTTP 转发次数）。

**不可称**：不能称「旧 ACK 在 B 进行中到达不覆盖 B」。B 在 A 的 ACK 释放之后才提交
（脚本在 A 异常后先 sleep 10s 才 refresh 并提交 B），本次运行不构成「陈旧 ACK 在新轮进行中迟到」
这一形态的证据；该形态目前只有模拟回归覆盖。转发器报告的 `forwarder_prompt_async_total=3`
含未匹配路径，**不能据此断言 A/B 的 POST 次数**；日志无精确的 forward 分类计数，故 POST 次数
记为未精确计数。释放时刻无独立时间戳，只能由上游 `Date` 头 + `hold_seconds=9.0` 推得。

**仍未实测**：跨轮陈旧 ACK、硬 RST / 真实客户端断开、Session 执行期 error。以上与模拟回归分列。

## 1. Redis 两项（真实 Redis 3 项 passed）

`REDIS_URL = os.environ.get("ASTRA_TEST_REDIS_URL")`（`services/task-platform/tests/test_gateway_data_plane.py:65`）。
db0 已存在 `astra:gateway:revoked_keys`，而 `test_redis_revocation_set_is_append_only_and_marked_ready`
会 `delete(REVOKED_KEYS_KEY)`（同文件 :1376），`REVOKED_KEYS_KEY` 为固定键 `astra:gateway:revoked_keys`
（`services/task-platform/app/gateway/runtime.py:68`，`RedisRuntimeStore` 无 prefix 参数）。因此必须走独立 db。
运行后 db0 `astra:gateway:revoked_keys` 仍存在（`EXISTS=1`），Celery 数据未被触碰；db15 残留 1 个同名键（隔离库，无害）。

## 2. Phase1A：旧契约校正（脚本改动）

**原因**：`passed` 条件要求 `smoke_task_status == "RUNNING"`（业务 Task 仍占用员工），
但脚本随后在同一员工 `phase1a` 上 `RuntimeService.start("T-LONG")`；`lifecycle.py:322-330` 的
occupied 检查（RUNNING / WAITING / pending_message_id 非空）必然抛
`RuntimeStateError("员工正在处理其他任务")`。这是脚本与当前产品契约的确定性冲突，与模型/网络无关。

**改动**（`tools/e2e/phase1a_real_opencode.py`，仅验收脚本）：

1. 记录真实 Session 标识 `result["session_id_observed"]`（:152）。
2. 记录真实经过时间 `smoke_wait_elapsed_seconds`（`time.monotonic()` 起止，不回填 timestamp）：本次 10.819s。
3. 进入 T-LONG 前先断言「业务 Task 仍 RUNNING/WAITING 且绑定同一 Session」：
   `smoke_task_still_occupied=true`、`smoke_session_stable=true`。
4. 用**现有** `RuntimeService.confirm_completion("T-SMOKE")` 人工确认释放员工
   （`services/task-platform/app/runtime/lifecycle.py:1071`），记录 `smoke_confirm_status=SUCCEEDED`、
   `smoke_confirm_elapsed_seconds=0.148`。

未放宽任何既有断言：`smoke_task_status` 仍在 confirm **之前**取值，原 `passed` 判定式一字未改。

**实测关键值**（真实 1.2.27 + opencode/space-bunny-free）：

```
smoke_task_status=RUNNING   smoke_file=PHASE1A_OK   session_status=SUCCEEDED
session_total_tokens=48768  session_tool_call_count=2   synthetic_context_in_session=true
old_session_status=INTERRUPTED   old_session_superseded_by=true   new_session_id_differs=true
longwrite_size_growing=30  longwrite_size_after_restart=30  longwrite_size_after_wait=30
old_session_stopped_writing=true
```

T-LONG 的真实长写入 + 显式 restart/取消链成立：旧 Session 被 INTERRUPTED 并被 superseded，
文件大小在 restart 后两次采样不再增长。`mcp` 字段返回空对象 `{}`，脚本未对该字段断言。

## 3. Phase1B：非旧契约，是 PATH 缺配置

**首跑失败的真实原因**（`~/.local/share/opencode/log/2026-09-30T160239.log`）：

```
ERROR service=mcp key=nexus-assistant type=local found
  command=["astra-assistant-mcp"] cwd=/Users/niuniu/程序/Astra
  error=Executable not found in $PATH: "astra-assistant-mcp"
```

`astra-assistant-mcp` 是 `services/task-platform/pyproject.toml:40` 声明的入口（`app.assistant.mcp_server:main`），
安装在 `.venv/bin/`。首跑我以 `.venv/bin/python -m pytest` 调用但未把 `.venv/bin` 放进 `PATH`，
MCP 未启动 → 助手无结构化提交工具 → `read_counts` 全 0、`summaries_found=0`，
三个真实 `service=llm ... agent=platform-assistant` 会话各在 step=2 `exiting loop` 后结束，纯文本作答。
**不是**脚本旧契约，也**不是**模型注入失败：把 `.venv/bin` 加入 `PATH` 后同模型直接通过。

**脚本改动**（`tools/e2e/phase1b_real_experience.py`，仅新增真实观测量，不改断言）：

- `timeout_budget_seconds` / `reconcile_elapsed_seconds`（`time.monotonic()` 实测）/ `summaries_found`
  写入 `report.json`（本次 240 / 78.59 / 3）。
- `assert len(summaries) == 3` 保持不变。

**实测关键值**：3 份 TaskSummary（T0/T1/T2）、4 条 `status=candidate` 经验（T0×2、T1×2、T2×0）、
`read_counts = {ses_requirement:65, ses_issue:5, ses_trivial:2}`（分页全量读取）、`task_statuses` 三项 SUCCEEDED。

## 4. 未覆盖项（如实记录）

- **Phase1B 不覆盖 in-flight disconnect / 晚 ACK。** 该脚本内的 fixture HTTP 源只是
  **Session message 数据源**，链路上没有 API 中转 gateway；对它加延迟无法触达
  disconnect/晚 ACK 语义。要真实覆盖必须让 1.2.27 真实转发 prompt 与 ACK 并在其中途施加延迟，
  按「不可 mock gateway 冒充真实」的约束，本次不做，故记为未覆盖而非伪造结论。
- Phase1A 的 `mcp` 返回空对象 `{}`（未断言），未进一步定位。

## 5. 未触碰确认

`git status --porcelain` 仅显示两个验收脚本 `M` 与未跟踪的 `evidence/`；未新增产品/测试改动，
未修改 README / acceptance-matrix / checks / fixes / limits-and-risks，未 `git add`/`commit`。