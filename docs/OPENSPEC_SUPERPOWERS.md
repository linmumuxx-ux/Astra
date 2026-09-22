# 项目内 OpenSpec + Superpowers 集成

Astra 把 OpenSpec 与 Superpowers 的开发能力直接放进仓库，**clone 后启动 OpenCode 即可使用**，
不依赖任何全局安装、`~/.config`、`~/.opencode` 或 Home 目录配置。

## 目录与事实源

```text
Astra/
├── opencode.json                         # 项目配置：instructions 指向 AGENTS.md 与 openspec/AGENTS.md
├── .opencode/
│   ├── commands/                         # /opsx-* 与 /sp-* 命令
│   ├── agents/code-reviewer.md           # 只读代码评审子代理
│   ├── skills/                           # 24 个项目级 skill（OpenSpec 9 + Superpowers 15）
│   ├── plugins/superpowers.js            # Superpowers bootstrap 注入（仅仓库根会话）
│   └── tools/openspec.mjs                # 自包含 OpenSpec CLI bundle（可提交产物）
├── openspec/
│   ├── AGENTS.md                         # OpenSpec 工作流约定
│   ├── schemas/spec-driven/              # 本项目固定 schema 与模板
│   ├── specs/                            # 归档后的当前规范
│   └── changes/                          # 进行中变更 + archive/
└── scripts/build_openspec_bundle.mjs     # 仅维护用：重新生成 bundle
```

仓库即唯一事实源。改动只需改仓库内文件，无需在开发机做任何安装或链接。

## OpenCode 如何加载

OpenCode 原生识别项目级目录，无需在 `opencode.json` 里逐个登记：

- 项目 skill：`.opencode/skills/<name>/SKILL.md`
- 项目命令：`.opencode/commands/<name>.md`
- 项目 agent：`.opencode/agents/<name>.md`
- 项目插件：`.opencode/plugins/*.js`（自动发现，已确认出现在 `opencode debug config` 的 `plugin`）

`opencode.json` 只声明 `instructions`，把 `AGENTS.md` 和 `openspec/AGENTS.md` 注入上下文。
修改这些文件后需要重启 OpenCode（配置只在启动时加载）。

## OpenSpec

- 命令：`/opsx-explore`、`/opsx-propose`、`/opsx-new`、`/opsx-continue`、`/opsx-ff`、`/opsx-apply`、`/opsx-verify`、`/opsx-sync`、`/opsx-archive`。
- skill：`.opencode/skills/openspec-*`。
- CLI：`.opencode/tools/openspec.mjs`。命令与 skill 内统一调用
  `node .opencode/tools/openspec.mjs <command>`，不依赖 PATH 上的 `openspec`。
- schema 由 `openspec/schemas/` 提供（CLI 的项目级优先级最高，已确认 `Source: project`）。
- 工作流：`需求/变更提出 → Spec → 设计/任务拆解 → 实现 → 验证 → 归档`。

### 重新生成 CLI bundle（维护用）

升级 OpenSpec 后，在一台装有 `esbuild`（`frontend/node_modules/.bin` 内已有）的机器上执行：

```bash
node scripts/build_openspec_bundle.mjs
```

脚本会把 OpenSpec 打包成单个自包含 `.mjs`，并内联两处运行时 `require`
（`package.json` 版本、`cross-spawn`），同时屏蔽 CLI 的重复自动执行。
OpenSpec 来源优先级：`ASTRA_OPENSPEC_PACKAGE` → `frontend/node_modules` → 全局 npm root。
普通开发者不需要运行此脚本，直接使用已提交的 bundle。

## Superpowers

- skill：`.opencode/skills/` 下的 15 个 Superpowers skill（`brainstorming`、`writing-plans`、
  `executing-plans`、`subagent-driven-development`、`test-driven-development`、
  `systematic-debugging`、`verification-before-completion`、`requesting-code-review` 等）。
- 命令：`/sp-brainstorm`、`/sp-plan`、`/sp-execute`、`/sp-debug`、`/sp-review`、`/sp-verify`、`/sp-finish`。
- agent：`code-reviewer`（`mode: subagent`，只读），由 `/sp-review` 使用。
- 插件 `.opencode/plugins/superpowers.js` 负责把 `using-superpowers` bootstrap 注入会话首条用户消息，
  让 skill 自动触发。**仅在 OpenCode 以仓库根为工作目录时注入**，且跳过平台助手 Runtime
  （其 Server 以 `ASTRA_RUNTIME_ROLE=platform-assistant` 标记），避免污染助手会话。

## 与 Astra 既有能力共存

- `platform-assistant` agent 与 `nexus-task-experience-review` skill 已收敛为项目级：分别位于
  `.opencode/agents/platform-assistant.md` 与 `.opencode/skills/nexus-task-experience-review/`。
- OpenSpec/Superpowers 的 skill、命令、agent 命名（`openspec-*`、`opsx-*`、`sp-*`、`code-reviewer`）
  与既有资源无冲突，加载无重复项。

## 验证（干净环境）

以下方式可在不依赖全局安装的情况下复现：

```bash
# 1) 屏蔽全局 Superpowers（~/.claude/skills）后，仍能列出项目内 24 个 skill
OPENCODE_DISABLE_EXTERNAL_SKILLS=1 OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1 opencode debug skill

# 2) 屏蔽全局 openspec 后，仍能用仓库内 bundle 跑完整流程
PATH=/usr/bin:/bin node .opencode/tools/openspec.mjs templates   # Source: project
PATH=/usr/bin:/bin node .opencode/tools/openspec.mjs new change demo
PATH=/usr/bin:/bin node .opencode/tools/openspec.mjs status --change demo --json
PATH=/usr/bin:/bin node .opencode/tools/openspec.mjs validate demo
PATH=/usr/bin:/bin node .opencode/tools/openspec.mjs archive demo --yes

# 3) 命令 / agent 被发现
opencode debug config    # 16 个 command、code-reviewer agent、superpowers 插件
opencode agent list
```

## 已知边界与风险

- 根目录 `.opencode/` 与 `opencode.json` 会被**同一 git worktree 内**的所有 OpenCode 进程继承。
  平台助手现在也以仓库根为加载上下文，插件已通过运行角色标记跳过其 bootstrap 注入；
  命令与 skill 对助手可见。生产环境请以项目级 `.opencode/agents/platform-assistant.md` 的
  `edit/write/bash` 拒绝作为主要约束（助手不再有独立 `opencode.json`）。
- 员工任务以独立 git worktree 运行（自带 `.git`），不会继承 Astra 根配置；但若任务 worktree 由
  包含本集成的提交创建，会带上一份 `.opencode/` 副本。是否需要为员工剥离该目录由后续决定。
- `opsx-archive` 命令内部使用 `mkdir -p` / `mv`，依赖 OpenCode 的 bash 环境；Windows 下需确保
  bash 语义可用（OpenCode 默认 bash 工具已满足）。核心 CLI 全部跨平台（仅依赖 `node`）。
- bundle 是从 `@fission-ai/openspec` 生成的可提交产物，升级时需按上文重新生成。