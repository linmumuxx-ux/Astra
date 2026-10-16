# Astra 1.0 验证记录

记录日期：2026-10-13。分支 `rewrite/astra-1.0`，基线见 `baseline.json`。**整体验收未通过，不可正式切换。** 唯一实施清单为 OpenSpec change 的 `tasks.md`；本报告只记录证据与适用边界。

## 已实际运行

| 验证 | 命令/证据 | 结果及边界 |
| --- | --- | --- |
| 统一静态、领域、迁移及前端检查 | `scripts/verify.py`；末次 `.venv/bin/python -m pytest tests/v1 -q --disable-warnings`、`apps/web` 的 `npm run build` / `npm run test:e2e:real` | Ruff、OpenSpec validate、157 项 Python 测试通过，5 项显式环境测试默认跳过；Vue 类型检查/构建通过，10 项真实 API 浏览器 E2E 通过。协议模拟测试不代表真实模型验证 |
| MCP Memory / Persona / SSE 追加回归 | `.venv/bin/python -m pytest -q --disable-warnings tests/v1/test_tools.py tests/v1/test_personas.py tests/v1/test_sse.py` | 12 项通过；真实 HTTP MCP 调新 API、Git 对象写读、uvicorn SSE 权限撤销均有覆盖 |
| 独立 MySQL 并发/领域集成 | `.venv/bin/python tests/v1/run_mysql.py`；`mysql-live-report.json` | MySQL 8.4.10，14 个测试文件（99 项）通过，静态 schema 1003 迁移通过；新建独立 datadir/schema，未接触原库。含锁等待 409、幂等重试、租约、权限、Memory、Persona、SSE。不是迁移 ETL 的同步 MySQL 验证 |
| 真实 OpenCode 工程探针 | `runtime-live-report.json`；`tests/v1/test_runtime_live.py` | OpenCode 1.18.35，真实 read/write/bash、五项独立测试、178 个原生事件、Session/worktree 恢复及 abort 回执。仅适配器隔离探针，不代替完整 Task 恢复/多员工业务链 |
| 真实 Persona / Git Memory / 定时唤醒 | `persona-live-report.json`；`tests/v1/test_persona_live.py` | 三个独立原生 Session；跨 Session 回忆、员工身份回复、真实 Redis/Celery/Beat Routine 唤醒及静默记档通过；16326 tokens/1803 micro-cost 来自原生事实。没有创建 Task，不代替工程/协作验收 |
| 真实工程业务与浏览器独立验收 | `execution-live-report.json`；显式 `ASTRA_LIVE_EXECUTION=1 ASTRA_LIVE_UI=1 ASTRA_LIVE_MODEL=provider/model` 执行 `tests/v1/test_execution_live.py` | 真实密码保护 Worker/Task API/原生执行/用量/结果 Inbox/浏览器逐条验收/幂等重放通过；完成后的原生证据另经真实浏览器读取通过。尚未覆盖完整自主验收/多员工恢复 |
| 独立员工原生验收 | `employee-review-live-report.json`；`ASTRA_LIVE_EMPLOYEE_REVIEW=1` 工程真实测试 | 1.19.0 上工程与 Persona 使用两个独立 Session，员工逐条引用真实原生工具证据完成 Task；完成后浏览器再次读取证据通过 |
| Linux SSH 原生工程 | `linux-runtime-live-report.json`；显式启用 `test_linux_runtime_live.py` | CentOS 7/glibc 2.17，1.19.0 实际读写/五项断言/断开转发后同 Session 恢复/独立复验与用量通过；不是远程 Task 工作区或全服务部署验收 |
| 一次性迁移工具 | `ASTRA_V1_MIGRATION_TEST_REPORT=docs/architecture/astra-1.0/migration-reconciliation-report.json .venv/bin/python -m pytest -q tests/v1/test_migration_etl.py tests/v1/test_migration_formal.py` | 27 项通过；隔离 fixture 的 12 行导入/逐类对账无差异。外部资产未核验，`production_source_accessed=false`，`cutover_allowed=false` |
| 页面证据 | `pages.md`、`evidence/` | 九类页面及移动端/403/授权撤销/Memory/Inbox 共 18 张真实浏览器截图。已视觉核查空间、Memory 与 Inbox；页面存在不代表所有业务能力完整 |

工程业务测试的后续只读历史证据验证复用了报告中的已完成 Task/Session，未重新执行模型；浏览器脚本为 `apps/web/e2e/review-live.mjs` 的只读模式。

真实 Persona 复验需显式设置 `ASTRA_LIVE_PERSONA=1 ASTRA_LIVE_CELERY=1 ASTRA_LIVE_MODEL=provider/model`。真实工程测试需 `ASTRA_LIVE_OPENCODE=1`。它们消耗模型额度，不在默认检查中隐式运行。证据目录保留在报告索引的本机位置，凭据未写入仓库。

## 覆盖情况

23 条新增 Requirement 的逐条实现/Scenario 映射及 18 项未完成实施任务，见 `../../openspec/changes/rebuild-astra-1-0/verification.md`。目前身份权限、幂等、消息隔离、正式交接、Routine、Persona fencing、Git Memory、Worker 绑定、历史读取、SSE 与页面基础操作有可复验证据。跨主机产物转移/Goal 跟踪、完整 Skill 成长、模型网关、附件/连接器、公司部署、真实全量迁移与完整多员工协作仍未通过，缺口见 `issues.md`。

## 检查限制

默认 Python 跳过项为真实工程探针、真实工程业务/浏览器、真实 Persona、真实 MySQL 锁等待及真实 Linux SSH，已分别独立运行上述适用测试。已执行 Linux 原生 Runtime/SSH 实测；尚未执行公司全服务部署、内网离线冷构建和灾备恢复；Python 全依赖还未锁定。构建仍有 Element Plus/Three.js 大块提示，Python 3.14 的 pytest-asyncio 有弃用提示，均不作为通过完整产品验收的依据。

真实返工验证见 `rework-live-report.json`：一个 Task、两个独立工程 Session、三个 Persona 回合，失败原生测试被拒后继承不可变产物修复并独立完成；原始标准与测试 SHA256 保持不变。schema 1003 夹具迁移再次逐类对账通过，不代表真实生产历史迁移。
