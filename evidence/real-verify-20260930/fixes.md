# 本轮修复（真实浏览器 / 真实运行时暴露）

## 1 指定员工的任务不自动启动（阻断固定业务流程）

**现象**：root 在 `http://localhost:5173/tasks` 创建任务并指定 `verify-20260930`，
页面长期停在「待执行 / 尚未创建 Session」，无任何手动启动入口；
同条件下我方 API 创建的 `T-20260930-66442B` 轮询 60 秒全程
`PENDING` / `current_session_id=None` / `workspace=None`。

**根因**：`backend/app/runtime/dispatcher.py` 的 `Dispatcher.claim_once()` 在为
待领取任务挑选员工时，无条件附加 `DigitalEmployee.auto_claim.is_(True)`。
创建任务时人工指定员工的任务同样要走这一步，因此当员工的
`auto_claim=false` 时永远选不到执行员工：既不会写 `TASK_ASSIGNED`，
也不会触发 `astra.dispatch` 里的 `RuntimeService.start`。
`auto_claim` 的语义只应约束「无人认领的任务池」。

**修复**（`backend/app/runtime/dispatcher.py`）：`task.employee_id` 有值时按员工 ID
精确匹配，未指定员工时才要求 `auto_claim=True`。IDLE、启用、并发 1、
执行环境 `AVAILABLE`、任务类型与分类兼容等既有校验全部保留；
后续仍由既有 `astra.dispatch` → `employee.auto_execute` 决定是否启动。
未新增状态、编排或架构层。

**生效**：修复并重启真实服务后，我方 API 任务被自动领取并创建真实 Session 与
真实 worktree；root 的 `T-20260930-73AB4C` 随即自动变 `RUNNING`
（Session `ses_f0d316562ffeaSckOd00zk1Brb`）。

**回归**（`backend/tests/test_runtime.py`）：

- `test_dispatcher_claims_task_assigned_to_employee_without_auto_claim`
- `test_dispatcher_keeps_unclaimed_pool_on_auto_claim`
- `test_dispatch_respects_employee_auto_execute[False/True]`
- `test_claimed_task_without_session_is_offered_again_for_start_retry`

## 2 原生 Workspace UI 无法回答权限请求（403）

**现象**：root 点击原生权限卡「允许一次」后 toast「请求失败 / [object Object]」，
权限卡不消失，任务停在 `WAITING`。

**根因（真实日志）**：`.astra/logs/backend.log` 记录
`POST /api/tasks/T-20260930-73AB4C/opencode/ses_.../session/ses_.../permissions/per_0f2d885f... → 403 Forbidden`。
OpenCode 1.2.27 原生 UI 用 `POST /session/{sessionID}/permissions/{permissionID}`
（该 Server `/doc` 中 operationId 为 `session.permissions.respond`，body
`{"response":"once"|"always"|"reject"}`）回答权限；而 Astra Workspace 代理的白名单
只有 `REPLY = ^/(question|permission)/([^/]+)/(reply|reject)$` 与
`SESSION_WRITE(prompt_async|message|abort|revert|unrevert|summarize|command)`，
于是落到兜底 `403 此接口不属于 Task Workspace 的权限范围`。

**修复**（`backend/app/api/workspace_routes.py`）：新增
`PERMISSION_REPLY = ^/session/([^/]+)/permissions/([^/]+)$`，与
`/permission/{id}/reply` 归一到同一个 `pending` 校验——必须属于本任务 Session 树、
只能对当前 Session 答复，随后走同一条转发与刷新路径。子 Session 权限仍按既有契约允许，
历史 Session 与业务终态拒写规则不变。

**生效**：API 专项真实 1.2.27 上 `POST …/session/{sid}/permissions/per_…` 返回 `200 true`，
pending 归 0，模型真实确认命令输出；root 浏览器复验同样通过。

**回归**（`backend/tests/test_session_workspace.py`）：

- `test_native_permission_reply_is_allowed_only_for_task_session`：用
  `httpx.MockTransport` 捕获上游，断言确切 `200`、`POST /session/ses_current/permissions/per_own`、
  body `{"response":"once"}`、query 带绑定 `directory`；异 Session 权限 403
  「请求不属于此任务 Session」，非本任务 Session 404。
- `test_native_permission_reply_is_denied_after_business_terminal[SUCCEEDED/CANCELED]`：
  业务终态下 legacy 与 `/permission/{id}/reply` 均 409。
- `test_bound_historical_session_rejects_native_writes[prompt_async/legacy permission/permission reply]`：
  任务自身已绑定的历史 Session 仍只读 403。

## 3 代码变更抽屉：请求身份缺失 + 永久加载

**现象**：root 先后在多标签与单标签下打开已 `SUCCEEDED` 任务的「代码变更」抽屉，
部分场景持续显示「正在读取 Git 变更…」。同期 backend 日志中**没有**对应的
`GET …/vcs/diff` 请求行，而同一接口命令行读取耗时 0.08s / 200。
root 复测中亦出现"切回累计又 20 秒超时"，且我持续写入触发的 uvicorn 热重载
与页面异常时间重合。

**结论**：后端 Diff 接口本身无缺陷；前端读取缺少上界，排队或无响应时会无限加载。
多标签/重载是否为唯一诱因**尚未确证**，按未验证限制记录，不做进一步归因。

**修复**（`frontend/src/views/TaskDetailView.vue`）：

1. `loadChanges()` 用 `AbortController` 给 Diff 读取 20 秒上界，超时给出可读错误
   「读取 Git 变更超时，请重试」，不再永久停留在加载态。
2. 补齐**请求身份**：切换模式前 `diffRequest?.abort()` 取消上一个请求，只有仍为当前
   `AbortController` 的请求能写 `changes` / `changesError` / `changesLoading` 与 `finally`。
   否则 `累计 → 未提交 → 累计` 时，第一个累计请求的晚到响应或超时错误会覆盖第三次请求的
   成功数据与加载态（原有 `mode` 判断在回到同一模式时失效）。
3. `onBeforeUnmount` 中止在途 Diff 请求（未断开全局 SSE）。

未新增共享状态层、未改原生 UI、未改事件架构。

**回归**（`frontend/e2e/task-diff-race.spec.ts`，真实组件 + 真实 Chromium + 真实 fetch，
只用请求拦截注入网络时序）：5 passed（1.2m）。

| 场景 | 断言 |
| --- | --- |
| 晚到的旧累计请求 | `累计→未提交→累计` 后数据仍为第三次请求结果，旧响应不覆盖，加载态与错误均无 |
| 晚到的旧超时 | 旧累计请求 30s 后才失败，不得覆盖成功数据/加载态/错误 |
| 当前请求超时 | 20s 上界后出现可读超时提示，加载态结束 |
| 切换模式取消 | 切到未提交后 15s 内观察到上一个累计请求被取消 |
| 卸载中止 | 关闭抽屉后 SPA 内导航离开任务页，在途 Diff 请求被取消 |

**before/after 对照**：移除请求身份与卸载中止、仅保留 20 秒上界后重跑，首项
「晚到的旧累计请求不得覆盖回到累计后的新数据」**明确失败**（旧响应覆盖了新数据）；
恢复当前实现后 5 项全通过。该对照证明测试确实覆盖被修复的行为。

**未采纳**：曾尝试在 `onBeforeUnmount` 关闭 store 事件流，经 root 独立审查驳回并已撤回
（该 store 的事件流为共享流，不属于本 change 范围）。

## 4 未重建 workspace-ui 产物

`frontend` 的 `npm run build` 会先执行 `build:workspace`，在本机依赖已安装时
重建 `frontend/public/opencode-workspace/1.18.31` 静态产物（53 删 53 新）。
该版本源码本次未改动，属 out-of-scope，已用 `git restore` + `git clean` 仅回滚
本次构建产生的 tracked/untracked 结果，未触碰 `1.2.27`，未影响其它用户改动。
最终 `vue-tsc -b` 与 `vite build` 改为不触发 workspace-ui 重建的方式单独执行并通过。
