# 检查与回归结果（最终）

均在 `fix/employee-task-flow-20260930` 工作区、全部改动就位后执行。
为避免 pytest 写 `__pycache__` 触发 uvicorn 热重载影响并行浏览器验收，
后端全量使用 `PYTHONDONTWRITEBYTECODE=1`。

## 后端

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Ruff（产品与测试） | `services/task-platform/`：`../.venv/bin/python -m ruff check app tests` | 通过 |
| Ruff（本次修改的验收脚本） | `services/task-platform/`：`../.venv/bin/python -m ruff check ../tools/e2e/phase1a_real_opencode.py ../tools/e2e/phase1b_real_experience.py` | 通过（最小修：1 处 import 分组、1 处行宽） |
| 后端全量（默认） | `services/task-platform/`：`PYTHONDONTWRITEBYTECODE=1 ../.venv/bin/python -m pytest -q --tb=short` | **397 passed、4 skipped**（70.06s） |
| 调度专项 | `pytest tests/test_runtime.py -k dispatch` | 5 passed |
| Workspace / 权限 / 历史 Session 专项 | `pytest tests/test_session_workspace.py -k "permission or historical"` | 8 passed |
| 员工 Serve 专项（3 次连续） | `pytest tests/test_employee_serve.py` | 11 passed / 26.0s、11 passed / 26.4s、11 passed / 28.6s |

### 关于 `test_two_employees_start_and_reuse_independent_serve` 的一次失败（如实记录，根因未定）

某一轮全量运行中该用例失败：`OpenCodeServerUnavailable … Serve 启动超时：OpenCode Server 不可用`。

- 事实：该用例在自身 `Settings(opencode_server_start_timeout_seconds=3)` 下同时冷启两个
  真实 Python stub Serve；失败时两个 stub 的 `.astra-opencode-server.log` **均为空**，
  没有可用日志可判定原因，因此**根因未确定**，不给出确定性结论。
- 后续：隔离重跑该文件 3 次均 11 passed；最终全量重跑 397 passed。
- 未改动产品代码，未放宽该用例 timeout，未修改任何断言。
- 与本次改动的关系：改动只涉及 `runtime/dispatcher.py`、`api/workspace_routes.py` 与前端，
  不触碰 `opencode_local_server.py`、`port_lock` 或其测试。

### 4 项 skipped（opt-in，与本轮真实验收分列）

| 用例 | 跳过原因 |
| --- | --- |
| `test_gateway_data_plane.py` Redis Lua / 吊销集合与哨兵 | 需 `ASTRA_TEST_REDIS_URL` |
| `test_real_opencode_phase1a.py` | 需 `ASTRA_REAL_OPENCODE=1` |
| `test_real_opencode_phase1b.py` | 需 `ASTRA_REAL_OPENCODE=1` |

这 4 项已由独立执行在真实环境单独跑通（真实 Redis 隔离库 db15、真实 OpenCode 1.2.27），
记录与原始日志见 `opt-in-summary.md` 及 `opt-in-redis/`、`opt-in-phase1a/`、`opt-in-phase1b/`。
默认全量仍保持 4 skipped，未修改跳过条件。

## 管理台

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 类型检查 | `frontend/`：`npx vue-tsc -b` | 通过（退出码 0） |
| 生产构建 | `frontend/`：`npx vite build` | 通过（退出码 0，5.39s） |

刻意使用 `npx vue-tsc -b` / `npx vite build` 而非 `npm run build`：后者会先执行
`build:workspace`，在本机依赖已安装时重建未改动的 `workspace-ui` 1.18.31 产物。
该批产物曾被产生过一次，已按 Git 干净起点用 `git restore` + `git clean` 仅回滚
（53 删 53 新），未提交产物、未触碰 `1.2.27`、未修改 `web/workspace-ui/` 源码。
`web/nexus/public/opencode-workspace` 与 `web/workspace-ui/` 最终均无改动。

## 浏览器 E2E（真实 Chromium，opt-in）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Diff 请求身份竞态回归 | `frontend/`：`ASTRA_DIFF_RACE_TASK=<真实任务> npx playwright test e2e/task-diff-race.spec.ts --project=chromium` | **5 passed**（1.2m），before/after 对照见 `fixes.md` |

其余 `frontend/e2e/*` 依赖默认 Chromium 缓存，本轮未全量执行；
root 的真实 Chrome 验收为主要浏览器证据。

## 真实运行时（非静态检查）

见 `acceptance-matrix.md`：真实 OpenCode Server 1.2.27、真实模型 `opencode/space-bunny-free`、
真实 Git worktree、真实 SQLite、真实 Chrome。真实 elapsed 超时注入见
`opt-in-timeout-ack/`。未使用 mock 冒充真实模型、原生问答、浏览器或公司远程。

## 未执行

- `scripts/verify.py` 全量门禁：其中 `e2e.py` 需要完整浏览器套件与默认 Chromium 环境，
  且 `ruff` 阶段不含 `scripts/`；本轮已按上表分项覆盖同等内容。
- 公司环境（Windows / Linux SSH）任何实测。
