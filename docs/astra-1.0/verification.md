# Astra 1.0 验证记录

记录日期：2026-10-13。分支 `rewrite/astra-1.0`，基线见 `baseline.json`。**整体验收未通过，不可正式切换。** 唯一实施清单为 OpenSpec change 的 `tasks.md`；本报告只记录证据与适用边界。

## 已实际运行

| 验证 | 命令/证据 | 结果及边界 |
| --- | --- | --- |
| 统一静态、领域、迁移及前端检查 | `ASTRA_E2E_BROWSER='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' .venv/bin/python scripts/verify.py` | Ruff、OpenSpec validate、127 项 Python 测试通过，3 项显式环境测试默认跳过；Vue 类型检查/构建通过，10 项真实 API 浏览器 E2E 通过。协议模拟测试不代表真实模型验证 |
| MCP Memory / Persona / SSE 追加回归 | `.venv/bin/python -m pytest -q --disable-warnings tests/v1/test_tools.py tests/v1/test_personas.py tests/v1/test_sse.py` | 12 项通过；真实 HTTP MCP 调新 API、Git 对象写读、uvicorn SSE 权限撤销均有覆盖 |
| 独立 MySQL 并发/领域集成 | `.venv/bin/python tests/v1/run_mysql.py`；`mysql-live-report.json` | MySQL 8.4.10，12 个测试文件通过，静态 schema 1001 迁移通过；新建独立 datadir/schema，未接触原库。含锁等待 409、幂等重试、租约、权限、Memory、Persona、SSE。不是迁移 ETL 的同步 MySQL 验证 |
| 真实 OpenCode 工程探针 | `runtime-live-report.json`；`tests/v1/test_runtime_live.py` | OpenCode 1.18.35，真实 read/write/bash、五项独立测试、178 个原生事件、Session/worktree 恢复及 abort 回执。仅适配器隔离探针，尚未证明完整 Task 业务执行链 |
| 真实 Persona / Git Memory / 定时唤醒 | `persona-live-report.json`；`tests/v1/test_persona_live.py` | 三个独立原生 Session；跨 Session 回忆、员工身份回复、真实 Redis/Celery/Beat Routine 唤醒及静默记档通过；16326 tokens/1803 micro-cost 来自原生事实。没有创建 Task，不代替工程/协作验收 |
| 一次性迁移工具 | `ASTRA_V1_MIGRATION_TEST_REPORT=docs/astra-1.0/migration-reconciliation-report.json .venv/bin/python -m pytest -q tests/v1/test_migration_etl.py tests/v1/test_migration_formal.py` | 27 项通过；隔离 fixture 的 12 行导入/逐类对账无差异。外部资产未核验，`production_source_accessed=false`，`cutover_allowed=false` |
| 页面证据 | `pages.md`、`evidence/` | 九类页面及移动端/403/授权撤销/Memory/Inbox 共 14 张真实浏览器截图。已视觉核查空间、Memory 与 Inbox；页面存在不代表所有业务能力完整 |

真实 Persona 复验需显式设置 `ASTRA_LIVE_PERSONA=1 ASTRA_LIVE_CELERY=1 ASTRA_LIVE_MODEL=provider/model`。真实工程测试需 `ASTRA_LIVE_OPENCODE=1`。它们消耗模型额度，不在默认检查中隐式运行。证据目录保留在报告索引的本机位置，凭据未写入仓库。

## 覆盖情况

23 条新增 Requirement 的逐条实现/Scenario 映射及 18 项未完成实施任务，见 `../../openspec/changes/rebuild-astra-1-0/verification.md`。目前身份权限、幂等、消息隔离、正式交接、Routine、Persona fencing、Git Memory、Worker 绑定、历史读取、SSE 与页面基础操作有可复验证据。任务真实启动/独立验收/返工跟踪、完整 Skill 成长、模型网关、附件/连接器、公司部署、真实全量迁移与完整多员工协作仍未通过，缺口见 `issues.md`。

## 检查限制

默认 Python 跳过项为真实工程、真实 Persona、真实 MySQL 锁等待，已分别独立运行上述适用测试。尚未执行公司 Linux/Windows/SSH、内网离线冷构建和灾备恢复；Python 全依赖还未锁定。构建仍有 Element Plus/Three.js 大块提示，Python 3.14 的 pytest-asyncio 有弃用提示，均不作为通过完整产品验收的依据。
