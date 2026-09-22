# OpenSpec 项目约定（Astra）

本目录是 OpenSpec 的规划根（planning home）。所有 spec 与 change 都提交在仓库内，
不依赖任何全局 OpenSpec 安装。

## 目录

- `openspec/specs/<capability>/spec.md`：已归档的当前事实规范。
- `openspec/changes/<change>/`：进行中的变更（proposal / specs / design / tasks）。
- `openspec/changes/archive/YYYY-MM-DD-<change>/`：已归档变更。
- `openspec/schemas/spec-driven/`：本项目固定的工作流 schema 与模板。

## CLI

OpenSpec CLI 以自包含 bundle 提交在仓库内，统一通过项目路径调用：

```bash
node .opencode/tools/openspec.mjs <command>
```

命令与 skill 已按此路径生成。不要改回裸 `openspec`，也不要依赖全局安装。

## 工作流

```text
需求/变更提出 → Spec → 设计/任务拆解 → 实现 → 验证 → 归档
```

对应命令：

- `/opsx-propose`：一次生成 proposal + specs + design + tasks。
- `/opsx-new` / `/opsx-continue` / `/opsx-ff`：分步或快速推进产物。
- `/opsx-apply`：按 tasks 实现。
- `/opsx-verify`：核对产物与任务完成度。
- `/opsx-sync`：把 delta spec 合并回主 spec。
- `/opsx-archive`：归档变更。

## 规则

- 动手前先查 `openspec/specs/` 是否已有同名 capability，避免重复定义。
- 变更行为必须写进 spec 的 requirement/scenario，不要把实现细节塞进 proposal。
- 归档前 delta spec 要么已 sync，要么明确说明不 sync。
- 本项目 schema 固定为 `spec-driven`，除非有明确理由再改 `openspec/schemas/`。

## 与 Superpowers 组合

OpenSpec 管"做什么、验收什么"，Superpowers 管"怎么分析、实现、调试、测试、评审"。
推荐：`/opsx-propose` 定契约 → `/sp-plan` 拆实施 → `/sp-execute` + TDD 实现 →
`/opsx-verify` 验证 → `/sp-review` 评审 → `/opsx-archive` 归档。