## Why

数字助手当前以独立目录 `nexus-assistant/` 作为专属 OpenCode Workspace，在其中单独维护 `opencode.json`、Agent、Skill 与 MCP。这让数字助手被错误地抽象成一个独立工程，与 Astra 项目级能力形成两套体系（Astra/Assistant 各自一套 Skill、MCP、Agent、配置），导致重复配置、配置漂移、生命周期复杂，也模糊了"能力属于项目、执行属于 Runtime、文件空间属于 Task"的边界。

数字助手本质上是 Astra 项目内置的一个 Agent（一个 OpenCode Session + 一组项目级能力），不是独立工程，也不需要独立 Workspace。本次调整移除"数字助手 Workspace"概念，把其 Skill / Agent / Command / MCP 收敛为 Astra 项目级能力，同时**保留**数字助手独立的 Runtime 与 Session，以确保与数字员工任务执行相互隔离。

## What Changes

- **BREAKING** 移除数字助手专属 Workspace 目录 `nexus-assistant/`（含 `opencode.json`、`AGENTS.md`、`.opencode/`、`assistant-context/`）。
- **BREAKING** 删除 `assistant_workspace_dir` 配置项及其解析属性；助手 OpenCode Server 不再 `chdir` 到独立工作区，改为以 Astra 项目根目录作为能力加载上下文。
- 将 `platform-assistant` Agent 迁移到项目级 `.opencode/agents/`，将 `nexus-task-experience-review` Skill 迁移到项目级 `.opencode/skills/`（迁移前去重，不产生副本）。
- 将 `nexus-assistant` MCP 与助手相关权限收敛到项目级 `Astra/opencode.json`；助手启动直接使用项目配置，不再生成/复制/动态拼装任何临时 `opencode.json`，也不通过 `OPENCODE_CONFIG` 指向独立目录。
- 保留数字助手独立 Runtime（独立 OpenCode Server 端口/凭据）与独立 Session，与数字员工 Task Runtime / Session 隔离。
- 明确助手权限边界：以 Astra 项目为加载上下文不等于允许修改 Astra 源码；`edit` / `write` / `bash` / `webfetch` 默认拒绝，平台操作统一走 `nexus-assistant` MCP。
- 清理 Workspace 相关引用：`ops/dev/preflight.py` 的助手运行区检查、`ops/dev/astra_service.py`、`deploy/systemd/astra-assistant-opencode.service`、三份 env 示例、部署文档与根 `AGENTS.md`。
- 更新 `superpowers.js` 插件中对 `nexus-assistant` 的隔离判断，确保不再为已删除目录保留特殊分支，同时不影响其他嵌套工作区。
- 更新测试与真实 OpenCode 脚本中硬编码的 `nexus-assistant/.opencode/...` 路径。

不移除：数字助手对话/事件/MCP/经验审核能力本身，以及 `app/assistant/` 的业务实现（orchestrator、MCP server、tool gateway、review、模型与 API）。

## Capabilities

### New Capabilities
- `platform-assistant-runtime`: 平台助手作为 Astra 项目级 Agent 运行——使用项目配置启动独立 OpenCode Runtime 与 Session、不创建/初始化 Workspace、默认禁止修改 Astra 源码、与数字员工 Task Runtime 隔离。覆盖 AC-01、AC-06、AC-07、AC-08。
- `project-capability-registry`: Skill、Agent、Command、MCP 以 Astra 项目为唯一定义来源，随 Git 统一版本管理；不存在助手本地的能力副本。覆盖 AC-02、AC-03、AC-04、AC-05、AC-10。
- `assistant-configuration`: 平台助手对外配置与界面不包含 Workspace 概念（无工作空间路径、初始化、上传、Git、文件管理）。覆盖 AC-09。

### Modified Capabilities
<!-- openspec/specs/ 当前为空，无既有 capability 需要修改 -->

## Impact

- **后端配置**：`services/task-platform/app/config/settings.py`（删除 `assistant_workspace_dir`、`resolved_assistant_workspace`、相关校验/注释）；`services/task-platform/app/assistant/server.py`（工作目录改为项目根）；`services/task-platform/app/assistant/client.py`。
- **后端启动/运维**：`services/task-platform/app/main.py`（编排器仍保留）、`ops/dev/astra_service.py`、`ops/dev/preflight.py`、`deploy/systemd/astra-assistant-opencode.service`。
- **项目配置**：根 `opencode.json`（新增助手 MCP）；`.opencode/agents/`、`.opencode/skills/`（迁入助手 Agent 与 Skill）；`.opencode/plugins/superpowers.js`。
- **能力资产**：删除 `nexus-assistant/`（`opencode.json`、`AGENTS.md`、`.opencode/agents/platform-assistant.md`、`.opencode/skills/nexus-task-experience-review/`、`assistant-context/`）。
- **配置样例/文档**：`.env.example`、`deploy/astra.env.example`、`deploy/astra.env.windows.example`、当时的 `docs/deploy/DEPLOYMENT.md`（已删除，现行说明是 `ops/deploy/DEPLOYMENT_GUIDE.md`）、`docs/product/design/PLATFORM_ASSISTANT.md`、`docs/architecture/OPENSPEC_SUPERPOWERS.md`、根 `AGENTS.md`。
- **测试**：`services/task-platform/tests/test_assistant.py`、`test_assistant_session_tools.py`、`test_recovery_summary.py`、`test_recovery_supervisor.py`、`test_employee_serve.py`、`test_real_opencode_phase1b.py`、`conftest.py`、`tools/e2e/phase1b_real_experience.py`。
- **接口/前端**：`/api/assistant/*` 与 `frontend/src/features/assistant/*` 行为不变；`frontend/src/views/settings/SystemSettings.vue` 的助手状态卡保持不变（当前无 Workspace 字段，需验证无回归）。
- **数据模型**：无 Workspace 字段需迁移；`assistant_*` 表与 `task_reviews` 保持不变。