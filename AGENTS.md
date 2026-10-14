# Nexus v1.0.1 开发约定

只放所有代码任务都要遵守的规则。OpenSpec 产物规则在 `openspec/config.yaml`，工具与集成细节见 `docs/OPENSPEC_SUPERPOWERS.md`；按需查阅，不要每轮加载整套教程。

本分支的产品是 **Nexus v1.0.1**。仓库里原有的 Astra 业务树（OpenCode Task / Worker、3D 数字办公、WeTalks、`backend/`、`frontend/`、`workspace-ui/`）只作为规范来源，不是本产品的运行入口，也不要迁进 Nexus。

## 工作原则

- 使用简体中文交流和编写项目文档；代码标识符、命令和 Conventional Commits 沿用仓库既有习惯。
- 先读真实代码、确认现状与需求，再做最小有效修改；不为臆测的问题增加状态层、抽象层或多套 fallback。
- 同一业务状态与规则只有一个事实源。修改前确认分支与 `git status`，不覆盖他人未提交改动。
- 没有验证证据不得声称完成。最终只汇报：原因、改动、验证、风险。

## 按变更规模选择流程

- **直接处理**：文案、局部样式、明确的小 Bug、纯重构、测试与文档，且不改变已约定行为。读相关代码后修改，运行针对性检查；不创建 OpenSpec change。
- **先定契约**：改变已约定的业务行为、既有 Spec，或涉及 API 契约、数据模型、权限、跨模块架构时，先查 `openspec/specs/` 是否已有对应 capability，再用 `/opsx-propose`（或分步命令）。纯重构不虚构业务 Requirement。`openspec/specs/` 里现存文档是 Astra 历史契约，Nexus 不修改它们。
- **一个计划**：用 OpenSpec 时以该 change 的 `tasks.md` 为唯一实施清单。Superpowers 只使用仓库里已经存在的 skill，不生成第二份同内容计划，也不虚构缺失的 skill。
- **完成闭环**：按 Scenario 核实代码与测试；影响 Spec 的变更执行 `/opsx-verify`，需要时 `/opsx-sync` 再 `/opsx-archive`。跑不了的验证如实标为未验证。

## 产品边界

- 新功能只写在 `nexus/`。不要把 Astra 的 Task、Run、Worker、OpenCode Session 或控制台页面接回产品路径。
- 前端是 `nexus/web`：Vue 3 + Element Plus。后端是 `nexus/api`：Python HTTP 服务，只通过 HTTP 调用 AgentScope，不内嵌、不 fork AgentScope。
- **AgentScope 2.0.10 Agent Service 是 Agent、Session、Skill、Knowledge 与对话记忆的唯一事实源。** Nexus 只保存员工目录、会话绑定和尚未被 Agent Service 接受的用户消息。不要在 Nexus 再实现一套 Agent、Session 或 Memory。
- Nexus 不提供模型、凭证或供应商配置界面。模型配置留在 AgentScope。
- 一位数字员工对应一个独立 Agent。一条私聊或一位员工在某个团队讨论中的上下文对应一条 Session。
- 员工之间的平等交流不使用 AgentScope Agent Team。Agent Team 是 Leader 派工给 Worker，不是对等同事。
- 同事联系走部署在 Agent Service 上的自定义工具 `contact_employee`：向对方 Session 的 inbox 投递 `HintBlock`，再由 MessageBus 的 wakeup 唤醒对方自己推理。Nexus 不编排脚本化的多 Agent 回复。

## 技术边界

- AgentScope 版本以 `nexus/deploy/agentscope.version` 为准，当前为 PyPI / GitHub tag `2.0.10`。接口说明以该 tag 的源码为准，见 `nexus/docs/agentscope-2.0.10.md`。
- 正式部署是独立的 AgentScope Agent Service + Redis。`create_app` 的 workspace 隔离使用 `IsolationPolicy.PER_SESSION`，这样同一员工的多条对话不会被 `(user, agent, workspace)` 折成一条 Session。
- 历史 Astra 数据不迁移。不要为了旧表、旧状态或旧前端保留双写和猜测式 fallback。

## 验证

先跑影响范围内的检查，再按范围扩大。Nexus 的常用命令见根目录 `README.md`。未实际运行的检查不得报告为通过。
