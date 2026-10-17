## 1. 能力迁移（项目级去重）

- [x] 1.1 将 `nexus-assistant/.opencode/agents/platform-assistant.md` 迁移到 `.opencode/agents/platform-assistant.md`，保留 frontmatter（`mode: primary`、`temperature`、`edit/write/bash/webfetch: deny`）与核心规则，删除 Workspace 相关叙述
- [x] 1.2 将 `nexus-assistant/.opencode/skills/nexus-task-experience-review/` 迁移到 `.opencode/skills/nexus-task-experience-review/`，内容保持不变
- [x] 1.3 检索确认 `.opencode/` 中无同名 Agent/Skill 冲突，确保为迁移而非新增副本
- [x] 1.4 删除 `nexus-assistant/` 整个目录（`opencode.json`、`AGENTS.md`、`.opencode/`、`assistant-context/`）

## 2. 项目配置

- [x] 2.1 在根 `opencode.json` 中新增 `nexus-assistant` MCP（`type: local`、`command: ["astra-assistant-mcp"]`、`enabled: true`），来源为原 `nexus-assistant/opencode.json`
- [x] 2.2 确认助手 Agent 的 `permission` 拒绝项仍在 Agent frontmatter 内声明，不依赖独立 `opencode.json` 的全局权限
- [x] 2.3 确认根 `opencode.json` 未引入任何指向 `nexus-assistant/` 的路径或 `OPENCODE_CONFIG` 覆盖

## 3. 后端运行改造

- [x] 3.1 删除 `services/task-platform/app/config/settings.py` 中 `assistant_workspace_dir` 字段与 `resolved_assistant_workspace` 属性，更新助手相关注释
- [x] 3.2 修改 `services/task-platform/app/assistant/server.py`：`workspace` 改为项目根（`settings.PROJECT_ROOT`），`main()` 不再校验助手工作区目录存在性
- [x] 3.3 在 `AssistantOpenCodeServerManager.process_environment()` 注入运行角色标记（如 `ASTRA_RUNTIME_ROLE=platform-assistant`）
- [x] 3.4 复核 `services/task-platform/app/assistant/client.py` 的会话标记与模型/Agent 取值仍生效（无需 Workspace 字段）
- [x] 3.5 更新 `.opencode/plugins/superpowers.js`：移除 `nexus-assistant` 特殊注释/分支，注入条件改为"项目根且非助手运行角色"
- [x] 3.6 确认 `services/task-platform/app/runtime/environment.py` 与 `services/task-platform/app/executors/opencode_local_server.py` 中助手端口保留逻辑不变

## 4. 运维与部署

- [x] 4.1 更新 `ops/dev/preflight.py` 的 `check_assistant_runtime()`：校验根 `opencode.json` 的 `nexus-assistant` MCP、`.opencode/agents/platform-assistant.md` 与 `astra-assistant-mcp` 入口，移除 `nexus-assistant` 目录校验
- [x] 4.2 检查 `ops/dev/astra_service.py` 中助手启动分支，移除对旧目录/配置的依赖
- [x] 4.3 更新 `deploy/systemd/astra-assistant-opencode.service`（工作目录/说明与项目根一致）
- [x] 4.4 清理 `.env.example`、`deploy/astra.env.example`、`deploy/astra.env.windows.example` 中的 `ASTRA_ASSISTANT_WORKSPACE_DIR`

## 5. 文档

- [x] 5.1 更新根 `AGENTS.md`：移除 `nexus-assistant/` 目录说明，说明助手为项目级 Agent
- [x] 5.2 更新 `docs/product/design/PLATFORM_ASSISTANT.md` 与 `docs/reports/verification/PLATFORM-ASSISTANT-2026-09-04.md`
- [x] 5.3 更新当时的 `docs/deploy/DEPLOYMENT.md` 中 `ASTRA_ASSISTANT_*` 与助手启动/日志/健康检查说明（该手册已删除，现行说明是 `ops/deploy/DEPLOYMENT_GUIDE.md`）
- [x] 5.4 更新 `docs/architecture/OPENSPEC_SUPERPOWERS.md` 中嵌套工作区隔离的描述

## 6. 测试与验证

- [x] 6.1 更新 `services/task-platform/tests/conftest.py`、`tests/test_assistant.py`（含隔离 Runtime 与迁移用例）、`tests/test_assistant_session_tools.py`
- [x] 6.2 更新 `tests/test_recovery_summary.py`（硬编码 `nexus-assistant/.opencode/skills` 路径改为项目级）、`tests/test_recovery_supervisor.py`、`tests/test_employee_serve.py`
- [x] 6.3 更新 `tests/test_real_opencode_phase1b.py` 与 `tools/e2e/phase1b_real_experience.py` 中从 `nexus-assistant/` 复制 Agent/Skill 的逻辑
- [x] 6.4 新增/调整测试：助手 Runtime 工作目录为项目根、不创建助手 Workspace、bootstrap 不注入助手会话、助手权限仍为 deny
- [x] 6.5 在 `services/task-platform/` 运行 `python -m ruff check app tests` 与相关 `pytest`
- [x] 6.6 运行 `python scripts/verify.py`，确认无残留 `nexus-assistant` / `assistant_workspace_dir` 引用，并检查 `git diff` 无无关改动