# 任务总结与经验沉淀验证记录

## 原因

已从当前调用链确认：复盘扫描未接入周期调度；人工确认没有同步原生 Session 终态；员工 MCP 和后台复盘均可写候选，且按 Session/Review 分别去重；经验验证只依赖任务成功和当前总结，没有核实引用。任务详情原先没有总结、复盘状态与重试入口。

同一任务生成大量经验的具体历史数量没有在正式数据库统计。已确认的放大机制是两个提交入口、仅同来源指纹去重，以及允许任意数量且无需说明独立价值；重试和新执行轮次可形成新的来源键。这些不能说明每次重试必然重复，原代码已有同轮次幂等保护。

## 改动

- 人工确认从主会话事实同步 Session 索引；以 Task 已完成为复盘调度依据，接入现有 Celery Beat/control 队列，复用 TaskReview 租约与轮次 ID。
- 员工只执行任务和查询/反馈知识，移除员工经验提交工具；总结与经验统一由后台复盘提交。
- Skill 明确目标、过程、结果、验证、遗留问题；允许零条经验，通常不超过两条，更多需说明独立价值。
- 复盘模型检索候选与正式经验后比较语义，合并候选或给正式知识补证据；正文指纹保护跨任务精确去重，保留代码大小写与缩进语义。
- 落库前核对原生消息、片段与连续摘录。验证须有具体工具输出或人工验证消息；失败命令不能标为通过。校验原因透传 MCP，模型可以修正重试。
- 正式正文不被后台改写；候选正文变化撤销旧验证标记。继续保留人工审核与正式知识发布权限。
- 任务详情新增总结与经验抽屉，展示状态、历史总结提示、关联知识和失败/超时重试。没有新增表或服务；保留历史字段与正式数据，不再重复写总结镜像字段或运行成功批量验证。

## 验证

| 类别 | 实际结果 | 证据 |
| --- | --- | --- |
| 后端 Ruff、脚本静态检查 | 通过 | 使用 backend/pyproject.toml 规则 |
| 针对性后端测试 | 78 通过；另有 4 项人工完成生命周期测试通过 | [targeted-tests.log](targeted-tests.log) |
| 全量后端测试 | 486 通过、4 跳过、1 既有失败 | [backend-full.log](backend-full.log) |
| 前端类型检查 | 通过，包含 workspace-ui 类型检查 | 实际运行 npm run type-check |
| 前端生产构建 | 通过，保留已有大 bundle 警告 | [frontend-build.log](frontend-build.log) |
| Chromium E2E | 203 通过、15 跳过 | [browser-e2e.log](browser-e2e.log) |
| 真实复盘模型 + MCP + 执行会话夹具 | 3 份总结；分页读取 65/5/2 条消息；无经验任务未生成候选；26.132 秒 | [assistant-fixture-report.json](assistant-fixture-report.json) |
| 真实员工 Session + 人工完成 + 真实后台复盘 + HTTP 发布 | 2 个真实 git worktree 任务、2 份总结、复用同一条已验证经验；普通查看者发布被拒绝；审核者发布成功；59.075 秒 | [real-session-report.json](real-session-report.json) |
| OpenSpec | change 与同步后的 capability 校验通过，6/6 实施项完成 | [场景核实](../../openspec/changes/optimize-task-experience-review/verification.md) |

真实端到端命令：

```sh
.venv/bin/python scripts/verify_task_review_real.py --model deepseek/deepseek-flash
```

该脚本使用临时 SQLite、独立 OpenCode 员工与助手进程、真实 Python 回归工具输出及隔离 HTTP API，不使用模型或 Session Mock。周期扫描调用正式调度函数；Celery Beat/Worker 的注册与调度配置另由针对性测试核实。首次真实运行暴露了 MCP 隐藏校验原因的问题，修复后重新运行通过。

## 风险

- `python scripts/verify.py` 在既有 `test_gateway_tables_are_registered_as_astra_tables` 失败：测试仍要求已不存在的 `gateway_config_versions`。原始未提交网关模型快照与当前文件一致，本次没有修改它或放宽断言。随后独立完成了类型检查、构建与浏览器验证。
- 真实验证仅覆盖本地 OpenCode 1.18.35 与 SQLite；MySQL 行锁、Linux SSH 远程全链路以及向正式 llm_wiki 的同步未实测。测试未写正式知识服务，HTTP 人工发布在隔离数据库中完成。
- 语义合并依赖复盘模型对适用条件、处理与验证方法的判断，仍保留人工审核。历史重复知识不会被批量删除或自动改写；已发布正文的补充仍由人工编辑。
