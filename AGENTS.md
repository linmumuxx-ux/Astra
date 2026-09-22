# AGENTS.md

## 沟通

始终使用中文与用户对话，思考过程也使用中文。

代码、命令、标识符和提交信息保持原有语言习惯，不要为了中文而改写。
提交信息沿用现有 Conventional Commits 风格，例如 `fix(runtime): ...`、`feat(library): ...`。

## 项目内开发能力（OpenSpec + Superpowers）

OpenSpec 与 Superpowers 随仓库提交在 `.opencode/` 与 `openspec/`，clone 后启动 OpenCode 即可使用，
不依赖任何全局安装、`~/.config`、`~/.opencode` 或 Home 目录配置。

- OpenSpec：`/opsx-propose`、`/opsx-new`、`/opsx-continue`、`/opsx-ff`、`/opsx-apply`、`/opsx-verify`、`/opsx-sync`、`/opsx-archive`、`/opsx-explore`；CLI 为 `.opencode/tools/openspec.mjs`。
- Superpowers：`/sp-brainstorm`、`/sp-plan`、`/sp-execute`、`/sp-debug`、`/sp-review`、`/sp-verify`、`/sp-finish`，以及 `.opencode/skills/` 下全部 skill。
- 组合方式见 `openspec/AGENTS.md`；集成说明与升级方式见 `docs/OPENSPEC_SUPERPOWERS.md`。

## 项目结构

- `backend/`：FastAPI + SQLAlchemy(async) + Celery + Alembic。`app/api` 路由、`app/runtime` 生命周期与恢复、`app/executors` 执行器、`app/assistant` 平台助手、`app/library_service.py` 数字图书馆。
- `frontend/`：Vue 3 + Vite 管理台。
- `workspace-ui/`：内嵌的 OpenCode 前端 fork，改动影响面大；动它之前先看 `workspace-ui/UPSTREAM.json` 的上游版本与改动清单。
- `.opencode/`：项目级 OpenCode 能力（`agents/`、`skills/`、`commands/`、`plugins/`）；`platform-assistant` 平台助手是项目内置 Agent，使用独立 Runtime、不拥有 Workspace。
- `scripts/`：统一 Python 入口（服务生命周期、preflight、verify、e2e、library e2e），不要再新增 bat / sh / PowerShell 包装。
- `configs/`、`deploy/`、`docs/`、`backend/alembic/versions/`。

## 常用命令

后端命令必须进入 `backend/` 执行：`pyproject.toml` 的 ruff 路径、`testpaths`、alembic 都相对于它。

```bash
# 服务生命周期（需要根目录 .env）
python scripts/astra_service.py dev [start|stop|restart|status]   # 开发
python scripts/astra_service.py pro [start|stop|restart|status]   # 正式，强制 MySQL + opencode_server
```

Windows 用 `.\.venv\Scripts\python.exe`，macOS/Linux 用 `.venv/bin/python`；README 只给了 Windows 写法。

```bash
# backend 目录内
python -m ruff check app tests
python -m pytest                                 # 全量，testpaths=tests
python -m pytest tests/test_runtime.py -k 名称    # 单个测试
python -m alembic upgrade head                   # 数据库迁移

# frontend 目录内
npm run type-check
npm run build        # 内含 workspace-ui 构建
npm run test:e2e
```

```bash
# 全量质量门禁：ruff + pytest + 前端 type-check/build + Chromium E2E
python scripts/verify.py
# 仅隔离 E2E（需 PATH 有 redis-server）：自建 sqlite + 临时 Redis + 前端 dev
python scripts/e2e.py
```

关键陷阱：

- `workspace-ui` 生产产物已提交在 `frontend/public/opencode-workspace`；未安装其依赖时 `npm run build` 直接复用，只有改 `workspace-ui/` 源码才需先 `node scripts/workspace_ui.mjs install` 再重建。
- `scripts/e2e.py` 使用 `scripts/fixtures` 里的假 `opencode` 与 `ASTRA_EXECUTOR_TYPE=opencode_cli_fallback`，不依赖真实 OpenCode / MySQL。
- 真实 OpenCode 测试默认 skip，显式开启才跑（会起真实 Server 调真实模型）：`ASTRA_REAL_OPENCODE=1 ASTRA_REAL_OPENCODE_MODEL=... pytest tests/test_real_opencode_phase1a.py`。
- `scripts/e2e_library.py` 需要真实 llm_wiki，默认每次加工最多等 300 秒，用 `ASTRA_LIBRARY_E2E_WAIT` 调整。
- Windows 开发模式 uvicorn 不带 `--reload`，改后端代码后要 `dev restart`；macOS/Linux 有 `--reload`。
- 正式模式拒绝 SQLite、非 `opencode_server`、seed demo，并在启动前执行 migration + preflight + 前端构建。
- Control Worker、Agent Worker、Beat 必须独立运行，不能合并成单个 `solo` Worker。

## 项目范围

Astra 负责长期任务的分配、执行、状态跟踪、人工介入和异常恢复。

平台管理 Task、Run、Employee 和 Runtime 状态。
任务具体怎么执行，由对应数字员工自己处理。

不要在 Astra 中增加 Agent 内部步骤、Skill、Tool 或工作流编排能力。

## Runtime

正式运行方式为 **OpenCode Server / Session / Event**。
`opencode run` 只作为独立的 CLI fallback。

修改 Runtime 相关代码前，先理清：

```text
Task → Run → Employee → Worker → OpenCode Session
```

注意：

- Task、Run、Employee、Session 状态要保持一致。
- 不要根据时间戳、日志、事件数量或前端状态反推 Runtime 状态。
- Runtime 展示以 `backend/app/runtime/presentation.py`（及 `task_status.json`）为准，前端状态文案与它共享。
- 修改生命周期时，要同时考虑失败、取消、超时、重试、重启、心跳丢失和恢复。
- 优先解决状态流转问题，不要靠 fallback 兜底。

## 数据兼容

历史异常数据优先通过 **Alembic migration、backfill 或一次性修复脚本**处理。

不要为了兼容旧数据长期保留：

- 新旧字段同时判断；
- 多层 fallback；
- 重复状态映射；
- 对异常历史数据的猜测处理。

能一次迁移的数据，就不要把兼容逻辑留在长期运行代码里。

## 修改要求

- 优先复用现有实现，能收敛就不要再加一套。
- 同一状态或业务规则不要在多个地方重复实现。
- 不顺手修改与当前任务无关的代码。
- 不覆盖用户已有修改。

## 完成前

先跑与本次改动最相关的检查，再根据影响范围扩大到 `scripts/verify.py`。
涉及核心 Runtime 或主要用户流程时，再运行对应 E2E（见上）。

检查 `git diff`，确认没有无关修改、调试代码和多余兼容逻辑。

最终说明：

**问题原因 → 修改内容 → 验证结果 → 剩余风险**