## 1. 版本契约

- [x] 1.1 设置、运行时门禁、快照写入和 Workspace API 只接受 1.18.35，并覆盖未知与已退役界面。
- [x] 1.2 更新 `test_opencode_server.py`、`test_session_workspace.py`、`test_service_gateway.py`、`test_serve_identity.py`；保留远程安装失败样本中的 `actual=1.2.27`。

## 2. 界面与安装

- [x] 2.1 将 `web/workspace-ui` 上游对齐 OpenCode `v1.18.35` 并完成真实构建。
- [x] 2.2 用 `opencode-ai@1.18.35` 的 `serve` 打开内嵌页并留下截图。
- [x] 2.3 删除 1.2.27、1.18.31、1.18.33 界面包及 1.2.27 构建工作流。
- [x] 2.4 安装器、远程默认版本和现行文档使用 1.18.35。

## 3. 仓库收敛

- [x] 3.1 环境文件只认 `ops/env/.env`；修正 Vite 输出目录、OpenSpec 目录约定和 Agent Service CI。
- [x] 3.2 删除静态 systemd 单元和安装脚本里重复的 Task MCP、管理台启动；迁移说明与 `astra_service.py` 的 `alembic upgrade head` 一致。
- [x] 3.3 删除未引用前端文件、韩文输入法补丁脚本和角色背面图。
- [x] 3.4 将 V0.4 指南、实现简报、旧设计、Runtime 终态说明和 OpenCode Server POC 移入 `docs/archive`。

## 4. 验证

- [x] 4.1 task-platform pytest 与 ruff、nexus-api、agent-service 测试、web type-check 与 build、workspace-ui 构建通过。
