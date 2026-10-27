## Why

公司只支持一个 OpenCode 版本。1.2.27 不再作为兼容目标，安装器、远程部署、运行时门禁和内嵌界面仍各自引用不同版本，历史 Session 还会在缺少版本时被写成默认旧版本。

## What Changes

- **BREAKING**：运行时只接受 OpenCode 1.18.35。白名单、最低版本和未知版本回退到 1.2.27 的行为删除。
- 内嵌 Workspace UI 只构建并发布 1.18.35。已记录的历史版本号保持不变；没有对应界面时显示「版本未知/界面已退役」。
- 安装器、远程部署默认值、设置和现行文档使用同一个版本。
- 环境文件只认 `ops/env/.env`。systemd 单元只由安装脚本生成。
- 未引用的前端文件、角色背面图和已退役的界面包删除。Astra V0.4 操作说明、实现简报、旧设计和 Runtime 终态说明归档。

## Capabilities

### New Capabilities

- `opencode-version`：唯一支持版本、历史版本保留，以及未知或已退役界面的可见结果。

### Modified Capabilities

- 无。不修改 `openspec/specs/` 中的历史契约。

## Impact

- Task 平台的版本门禁、Session 环境快照和 Workspace API。
- `web/workspace-ui` 上游源与 `web/nexus/public/opencode-workspace/1.18.35/`。
- `ops/deploy/install_nexus.sh`、`ops/dev/astra_service.py`、`ops/dev/load_env.sh` 和部署文档。
- 不改 Alembic、助手模块、CLI fallback，也不裁剪上游核心。
