## Context

安装器、远程部署和运行时原先用最低版本加白名单判断 OpenCode。Workspace UI 在快照没有版本时写入 1.2.27。公司决定只支持 1.18.35。

## Goals / Non-Goals

**Goals:**

- 新启动的 OpenCode 必须报告 1.18.35，否则版本检查失败。
- 健康检查没有版本时，新快照记为 `unknown`，不填当前版本。
- 已保存的版本字符串不被迁移或接口改写。
- 缺少界面包时返回空的界面地址和「版本未知/界面已退役」。

**Non-Goals:**

- 不回填或重写历史 Session。
- 不改 Alembic、助手模块和 CLI fallback。
- 不把本 change 归档进 `openspec/specs/`。

## Decisions

1. 版本事实源是设置项 `opencode_server_version`，默认 `1.18.35`。安装器常量、远程部署默认值和 `web/workspace-ui/UPSTREAM.json` 使用同一版本。关闭检查只能用显式开关，不能用 `0.0.0`。
2. 界面选择只看快照里的版本和对应 `index.html`。不存在第二个默认界面版本。
3. 环境文件只读 `ops/env/.env`。安装脚本自己生成 systemd 单元，并继续由 `astra_service.py` 在启动前执行 `alembic upgrade head`。Task MCP 和管理台只由该开发监督进程启动。
4. Workspace UI 从 OpenCode tag `v1.18.35` 构建。上游构建无法完成时停止，不改名旧产物。

## Risks / Trade-offs

- 已记录为 1.2.27、1.18.31 或 1.18.33 的 Session 不能再打开内嵌界面。版本号仍可查看。
- 未报告版本的新 Server 不能开始新 Session 的版本检查。快照会留下 `unknown`。
