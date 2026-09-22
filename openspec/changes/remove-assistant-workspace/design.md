## Context

当前数字助手以独立目录 `nexus-assistant/` 作为专属 OpenCode Workspace：`backend/app/assistant/server.py` 启动 OpenCode Server 前 `os.chdir(resolved_assistant_workspace)`，由该目录下的 `opencode.json`（权限 + `nexus-assistant` MCP）与 `.opencode/`（`platform-assistant` Agent、`nexus-task-experience-review` Skill）提供能力。该目录还包含未使用的 `assistant-context/` 占位。

关键事实：

- `Workspace` 在 Astra 中是**执行文件操作的工作目录**。数字员工 Task 需要（创建/修改文件、Git、编译、测试），因此 `LocalOpenCodeServerExecutor` 要求员工工作区自带 `opencode.json`（`discover_workspace_config`）。
- 数字助手不执行工程任务，不需要文件空间，其存在意义是隔离"Agent 能改代码"这一风险，而不是承载文件操作。
- 数字助手与数字员工是两套东西：Task 执行链路（Task → Session → Summary → Experience → Knowledge）不包含数字助手。
- `app/assistant/` 的业务实现（orchestrator、MCP server、tool gateway、review、模型、API）与本次调整无关，必须保留；`app/assistant/review.py` 还被 `runtime/recovery.py` 复用于任务经验审核。
- `openspec/specs/` 当前为空，无既有 capability 需要修改。

约束：

- 保留数字助手独立 Runtime 与 Session，与数字员工 Task Runtime / Session 隔离。
- 能力（Skill / Agent / Command / MCP）唯一来源为 Astra 项目级结构，保留 Git 统一版本管理，禁止全局安装或临时配置。
- 数字助手以项目为加载上下文，但默认不得修改 Astra 源码。

## Goals / Non-Goals

**Goals:**

- 删除数字助手独立 Workspace 概念，助手 OpenCode Runtime 以 Astra 项目根目录作为能力加载上下文。
- 将 `platform-assistant` Agent、`nexus-task-experience-review` Skill、`nexus-assistant` MCP 收敛到项目级并去重。
- 保留助手独立 Runtime / Session 与既有对话、事件、经验审核能力。
- 明确并保持助手权限边界（禁止改源码、平台操作走 MCP）。
- 清理配置项、启动脚本、部署物、文档与测试中的 Workspace 引用。

**Non-Goals:**

- 不改变数字员工 Task 执行架构（Task / Workspace / Runtime）。
- 不移除 `app/assistant/` 业务实现或 `/api/assistant/*`、前端助手抽屉。
- 不引入 Workspace 相关数据库字段，也不做数据迁移（当前无此类字段）。
- 不把能力安装为 OpenCode 全局能力，也不为助手保留任何临时 `opencode.json`。
- 不合并数字助手与数字员工的 Runtime。

## Decisions

### D1：助手不拥有 Workspace，工作目录改为 Astra 项目根
助手 OpenCode Server 的 `cwd` 由 `resolved_assistant_workspace`（`nexus-assistant/`）改为 Astra 项目根（`settings.PROJECT_ROOT`）。OpenCode 从项目根发现 `opencode.json`、`.opencode/` 与 `.opencode/skills`，即"Git 仓库中的项目配置即运行配置"。

- 备选：保留一个空的 `nexus-assistant/` 仅作 `cwd`。否决——仍然保留独立 Workspace 概念，并需要维护专项配置。
- 备选：为助手生成临时 `opencode.json` 指向项目能力。否决——违反配置来源唯一，易产生漂移。

### D2：删除 `assistant_workspace_dir`，直接复用项目根解析
删除 `assistant_workspace_dir` 字段与 `resolved_assistant_workspace` 属性；助手工作目录取自 `settings` 中已有的 `PROJECT_ROOT`（`Path(__file__).resolve().parents[3]`），并允许通过显式的项目根配置覆盖，避免依赖进程当前目录。

- 备选：新增独立 `ASTRA_PROJECT_ROOT` 必填项。暂不强制；沿用既有 `PROJECT_ROOT` 推导，保持部署简单，必要时再引入显式覆盖。
- 取消 `AssistantOpenCodeServerManager.workspace` 对目录存在性的强校验（项目根必然存在）。

### D3：助手能力迁移到项目级并去重
- `nexus-assistant/.opencode/agents/platform-assistant.md` → `.opencode/agents/platform-assistant.md`（内容保留，仅去掉 Workspace 叙述）。
- `nexus-assistant/.opencode/skills/nexus-task-experience-review/` → `.opencode/skills/nexus-task-experience-review/`。
- `nexus-assistant/opencode.json` 中的 `nexus-assistant` MCP 定义迁移到根 `opencode.json`；助手 Agent 自身的 `permission`（`edit/write/bash/webfetch: deny`）继续在 Agent frontmatter 中声明。
- 迁移前核对是否已有同名能力，禁止形成副本；迁移后删除 `nexus-assistant/` 整目录（含未使用的 `assistant-context/`）。

### D4：能力定义项目级、授权 Agent 级
项目级能力对所有 Agent 可见，但可用范围由 Agent 权限决定。平台助手仅启用平台查询/操作相关 Skill 与 `nexus-assistant` MCP；不通过复制能力实现隔离。

### D5：保留独立 Runtime / Session
保留 `assistant_opencode_port`（默认 4097）、独立 hostname/凭据与 `astraRuntime: platform-assistant` 会话标记，继续在端口占用检测（`runtime/environment.py`、`executors/opencode_local_server.py`）中保留助手端口。助手与员工 Runtime 故障互不影响。

### D6：助手权限边界不变
即使工作目录是项目根，助手 MUST NOT 修改源码。`edit` / `write` / `bash` / `webfetch` 默认拒绝；平台变更通过 `nexus_*` MCP 先 prepare 再确认。

### D7：助手 Runtime 不接收 Superpowers bootstrap
`superpowers.js` 当前以"仅 `directory === ASTRA_ROOT` 才注入 bootstrap"来隔离 `nexus-assistant`。助手改用项目根后，该条件会对助手 Runtime 成立，导致把开发工作流注入面向用户的助手会话。改为由助手 Server 在启动环境注入运行角色标记（如 `ASTRA_RUNTIME_ROLE=platform-assistant`），插件仅在项目根且非助手运行时注入 bootstrap。插件中针对 `nexus-assistant` 的注释与特殊分支同步移除。

- 备选：让助手接受 Superpowers bootstrap。否决——与助手"事实来自工具、禁止编造"的定位冲突，属噪声。
- 备选：按会话元数据区分。`experimental.chat.messages.transform` 不提供稳定会话元数据，故用启动环境变量最小侵入。

### D8：项目级 MCP 的可见性
根 `opencode.json` 增加 `nexus-assistant` MCP 后，所有在项目根运行的会话（含开发者会话）都会加载该 MCP。数字员工在各自工作区 `opencode.json` 下运行，不受影响。接受该副作用；需要时由 Agent 级 `tools` 授权收紧。

## Risks / Trade-offs

- [助手的加载上下文变为含完整源码的项目根] → 通过 Agent 级 `edit/write/bash/webfetch: deny` 约束；平台操作走 MCP。需在测试中断言权限未被放宽。
- [根 `opencode.json` 新增 MCP 影响开发者会话] → 仅在项目根生效，不影响员工工作区；必要时以 Agent `tools` 收紧。若启动 `astra-assistant-mcp` 依赖缺失，仅该 MCP 不可用，不阻断会话。
- [插件 bootstrap 隔离条件变化导致助手收到开发工作流] → D7 的运行角色标记；需覆盖一条测试/校验。
- [能力迁移遗漏引用] → 全文检索 `nexus-assistant`、`assistant_workspace_dir`、`resolved_assistant_workspace`、`astra-assistant-mcp`，确保 preflight、systemd、env 示例、文档、测试同步。
- [预检、启动脚本仍校验旧目录] → `preflight.check_assistant_runtime` 改为校验项目根 `opencode.json` 的 MCP 与 `.opencode/agents/platform-assistant.md`。

## Migration Plan

1. 迁移能力：复制 `platform-assistant` Agent 与 `nexus-task-experience-review` Skill 到项目级目录，去重后删除 `nexus-assistant/`。
2. 改造运行：更新根 `opencode.json` MCP、助手 Server 工作目录、settings，新增运行角色标记。
3. 清理引用：preflight、astra_service、systemd、env 示例、文档、AGENTS.md。
4. 更新测试与真实 OpenCode 脚本中的硬编码路径；运行相关检查。

回滚：本次为代码/配置变更，无数据库迁移。回滚即从 Git 恢复 `nexus-assistant/` 与相关改动。

## Open Questions

- 是否需要在部署层显式引入 `ASTRA_PROJECT_ROOT`（当前沿用 `PROJECT_ROOT` 推导）？
- 项目级 `nexus-assistant` MCP 是否需要在开发者 Agent 上默认禁用（Agent 级 `tools`）？
- `superpowers.js` 运行角色标记的变量名与取值约定（`ASTRA_RUNTIME_ROLE=platform-assistant` vs 布尔 `ASTRA_ASSISTANT_RUNTIME`）。