# Astra 开发约定

只放所有代码任务都要遵守的规则。OpenSpec 产物规则在 `openspec/config.yaml`，工具与集成细节见 `docs/OPENSPEC_SUPERPOWERS.md`；按需查阅，不要每轮加载整套教程。

## 工作原则

- 使用简体中文交流和编写项目文档；代码标识符、命令和 Conventional Commits 沿用项目原有习惯。
- 先读真实代码、确认现状与需求，再做最小有效修改；不为臆测的问题增加状态层、抽象层或多套 fallback。
- 同一业务状态与规则只有一个事实源。修改前确认分支与 `git status`，不覆盖他人未提交改动，不直接在 `master` 开发。
- 没有验证证据不得声称完成。最终只汇报：原因、改动、验证、风险。

## 按变更规模选择流程

- **直接处理**：文案、局部样式、明确的小 Bug、纯重构、测试与文档，且不改变已约定行为。读相关代码后修改，运行针对性检查；不创建 OpenSpec change。
- **先定契约**：改变已约定的业务行为、既有 Spec，或涉及 API 契约、数据库模型、Runtime 状态与恢复、权限、跨模块架构时，先查 `openspec/specs/` 是否已有对应 capability，再用 `/opsx-propose`（或分步命令）。纯重构不虚构业务 Requirement。
- **一个计划**：用 OpenSpec 时以该 change 的 `tasks.md` 为唯一实施清单。Superpowers 的分析、调试、TDD、评审 skill 按需调用，不生成第二份同内容计划，也不要求每个小任务都走头脑风暴或子代理流程。
- **完成闭环**：按 Scenario 核实代码与测试；影响 Spec 的变更执行 `/opsx-verify`，需要时 `/opsx-sync` 再 `/opsx-archive`。跑不了的验证如实标为未验证。

## 不可混淆的架构边界

- Astra 管理 Task 的业务闭环、员工分配、运行观察、人工介入与异常恢复；任务内部的 Agent、Skill、Tool 与执行步骤由数字员工决定，平台不重复编排。
- **Task 是业务闭环；OpenCode Session 是执行事实源；RuntimeSession 只存绑定、终态与用量索引。** 旧 Run 表已在 `0024_drop_legacy_run_models` 删除，不要重建 Run 状态机、消息副本，也不要靠前端状态、时间戳或事件数量反推 Runtime 终态。状态文案以 `backend/app/runtime/presentation.py` 与 `task_status.json` 为准。
- 正式执行走 OpenCode Server / Session / Event，CLI fallback 仅用于隔离测试或应急。改生命周期须覆盖取消、重试、人工确认、超时、断线与恢复，并保证旧轮次结果不覆盖新轮次（`superseded_by`）。
- 平台助手以 `ASTRA_RUNTIME_ROLE=platform-assistant` 标记，用独立 Runtime、不持有工作区，权限为只读查询 + prepare 确认；数字员工在独立 git worktree 中工作，按需保留自己的 OpenCode 配置。不要混用两者的提示词、权限与运行目录。
- 历史数据问题优先一次性迁移、回填或修复脚本，不把旧字段兼容和猜测式 fallback 留在长期代码里。

## 技术边界

- `backend/`：FastAPI + SQLAlchemy async + Celery + Alembic，命令在 `backend/` 内执行。数据库事务只做短状态更新，不在行锁内做 OpenCode、SSH 或网络 I/O。
- `frontend/`：Vue 3 + Element Plus，优先原生组件，同类控件尺寸统一。主题以 `frontend/src/styles/tokens.css` 和 `element-plus-theme.css` 为准，不在页面重复定义主题。
- `workspace-ui/`：内嵌 OpenCode 前端 fork，动之前先看 `UPSTREAM.json` 的上游版本与改动清单；不因改管理台而顺手重建它。

## 验证

先跑影响范围内的检查，再按范围扩大到 `python scripts/verify.py`。区分静态检查、模拟测试与真实环境验证，未实际运行的检查不得报告为通过。服务与常用命令见 `README.md`。
