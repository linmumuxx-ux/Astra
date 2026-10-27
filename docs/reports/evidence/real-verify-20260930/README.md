# 真实验收证据索引（2026-09-30）

分支：`fix/employee-task-flow-20260930`。
本轮用户起始提交：`e9189ab`（`fix(runtime): keep employee tasks open until human completion`）；
其上游父提交为 `f7aed8b`。
本目录只保存脱敏后的 Markdown 验收结论；原始长日志、报告 JSON 与临时注入 harness
按 `.gitignore` 仅本地保留，不入 Git。

## 运行环境

| 项 | 值 |
| --- | --- |
| 管理台 | `http://localhost:5173`（本地开发态，免登录入口） |
| API | `http://127.0.0.1:8100/api/health` |
| OpenCode Server（公共 / 助手） | 127.0.0.1:4096 / 4097，`/global/health` = `1.2.27` |
| 员工 Serve 端口 | 17311 / 17312 / 17313 / 17314 / 17315，`/global/health` 均 `1.2.27` |
| 员工实际模型 | provider `opencode`，model `space-bunny-free`（真实免费额度，真实回复；无 mock） |
| OpenCode 二进制 | 临时安装的 `opencode-ai@1.2.27`（仓库外临时目录，未提交） |

`opencode` 全局 CLI 为 1.18.33，仅用于本机工程委托，**不作为 1.2.27 验收证据**。

## 验收 fixture（隔离，不影响既有员工）

| 类型 | 标识 | 说明 |
| --- | --- | --- |
| 浏览器验收员工 | `verify-20260930` / 验收员工 20260930 | 端口 17311，隔离 Git 项目 |
| API 专项员工 | `verify-api-20260930` / API 验收员工 20260930 | 端口 17312，独立隔离项目 |
| 失败注入员工 | `verify-fail-20260930` / 失败注入员工 20260930 | 端口 17313 |
| 启动失败员工 | `verify-boot-20260930`、端口冲突员工 `verify-port-20260930` | 端口 17314 / 17315 |
| 分类 | `CAT-87CF473E`、`CAT-ECD5133D`、`CAT-B3F648DB`、`CAT-5F140C75`、`CAT-5CF652C7` | 真实验收专用 |
| 隔离 Git 项目 | 仓库外临时目录 `acceptance-project` / `-api` / `-fail` | 各含 `opencode.json`（`permission.bash=ask`） |

`astra-01` 的执行环境字段在验收准备期间被临时改过一次，已**完整还原**为
`opencode` / `deepseek/deepseek-v4-flash` / 14096 / `./workspaces`。

## 文件

- `acceptance-matrix.md`：六项验收逐条结论、通过/未验证标记与证据指向。
- `fixes.md`：本轮定位并修复的缺陷、根因、关键 diff 与回归。
- `limits-and-risks.md`：明确未验证项、限制与风险（含 OpenCode 自然挂起）。
- `checks.md`：静态检查与回归执行结果（最终）。
- `opt-in-summary.md`：4 项 opt-in 真实环境联调（真实 Redis db15、真实 1.2.27 Phase1A/1B）。
- `opt-in-redis/`、`opt-in-phase1a/`、`opt-in-phase1b/`、`opt-in-timeout-ack/`：原始长日志、
  报告 JSON 与临时注入 harness，**仅本地保留**（见 `.gitignore`），其脱敏结论已写入
  `opt-in-summary.md`。

## 脱敏声明

本目录及提交内容中不包含任何 API key、token、password、credential、auth 值、
`runtime_context` / `ctx_` 运行时上下文令牌；仅记录"存在/不存在"。
