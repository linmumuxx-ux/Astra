# 限制、未验证项与风险

## 明确未验证

| 项 | 原因 |
| --- | --- |
| 公司环境（Windows / Linux SSH）远程 worktree 校验与 1.2.27 流程 | 本机无公司 SSH 配置与凭据，未做任何远程实测。远程相关只有以命令文本为输入的既有回归，不冒充公司实测 |
| 跨轮陈旧 ACK（新轮进行中才到达） | **未覆盖**：真实 ACK 延迟注入已成立，但其 ACK 释放在新一轮提交之前，不构成该形态证据；目前仅模拟回归覆盖。首次注入因路径匹配错误（`forwarder_prompt_async_total=0`）前提不成立，已更正后重跑 |
| 真实客户端硬断 / RST | **未覆盖**：真实注入只做了「延迟 + 释放」，未构造强制 RST；`release_error` 路径存在但未被触发 |
| ACK 的 POST 次数 | 转发器 `forwarder_prompt_async_total=3` 含未匹配路径，无法据此断言 A/B 的 POST 次数；仅原生消息各 1 条为明确证据，POST 次数记为未精确计数 |
| Session execution error（真实轮次失败） | **未覆盖**：可用的真实失败只有 Serve 启动失败（端口被占，任务层失败），不能替代 Session 执行错误；模型/provider 错误注入未生效，未触发执行期错误 |
| 浏览器侧真实断线重连 | root 未做；本轮以真实 Server 断线 + `POST /reconnect` 证明 Session 不丢、不重复提交，但那次断线发生在响应完成之后，真实 in-flight 断线仍未验证 |
| Session 执行期 error（真实轮次失败） | 注入不存在的模型 / 不存在的 provider **未生效**：原生实际仍运行 Space Bunny Free 并成功回复，未触发 Session 执行 error（不断言原生 fallback）；真实失败只有 Serve 启动失败（任务层），不可替代 |

## 风险与待处理限制

1. **OpenCode 自然挂起未定位（真实，重要）**
   root 浏览器第二轮（22:55:10）只有一次 `prompt_async=204`，随后 native assistant
   `parts` 为空、无 completed、无 error、token 0，native 与 proxy status 均为 busy，
   SSE 每 8 秒仅 `connected`；定位到 native `service=llm stream` 后首个 part 之前，
   model/agent/variant 与首轮一致。OpenCode 日志
   `~/.local/share/opencode/log/2026-09-30T144551.log` 第 2075 与 3732-3740 行相关。
   **未确定 provider 或 runtime 根因，因此不宣称第二轮通过。** Astra 侧表现符合契约：
   任务保持可继续，未被误判完成。当前缺少对"原生长时间无首 part"的观测与提示，
   属于待处理限制。

2. **代码变更抽屉的加载态**
   已加 20 秒上界、可读失败提示与请求身份（晚到响应/超时不得覆盖当前请求结果）。
   早前观察到的永久 Loading 中，热重载确实参与（backend 日志可见
   `WatchFiles detected changes ... Reloading` 与页面异常时间重合），
   但触发条件未最终确定，**不归因于 SSE 数量、浏览器连接数或 IAB**。
   root 在最终 controller 版上以单标签真实 Chrome 复核：累计与未提交均正常，
   切回累计正常，无 Loading、无超时。

3. **传统办公室场景未挂载**
   本分支的真实 router（`frontend/src/router/index.ts`）与 Dashboard 均无传统办公室场景的
   路由或切换入口，因此该场景的浏览器一致性无法验证，也未新增挂载来扩大范围。
   当前可达页面为首页、任务列表/详情、员工列表/详情、数字图书馆、API 中转、设置。

4. **上游事件流生命周期**
   `TaskDetailView` 的 `store.connectEvents()` 未在离开页面时关闭，
   每访问一次任务页会留下一条常驻 SSE。root 审查明确要求不改动共享事件流，
   故本 change 不处理，仅记录。

5. **凭据类信息**
   本轮未读取 `.env` 正文；仓库根 `.env` 中的
   `ASTRA_LLM_WIKI_API_TOKEN`、`ASTRA_GATEWAY_MASTER_KEY`、
   `ASTRA_GATEWAY_CONTROL_CREDENTIALS` 均为**存在**状态，本记录与提交内容不含其值。
   `runtime_context` / `ctx_` 运行时上下文令牌在所有证据中一律不落盘。

6. **独立注入的隔离与清理（已完成）**
   ACK / timeout 注入使用独立临时 SQLite、`ASTRA_RUNTIME_DIR`、`free_port()` 端口与独立员工 id
   （`astra-inject-*`），超时预算 12s / 控制 5s 只经**独立 Python 子进程 `os.environ`** 生效，
   进程退出即消失；项目 `.env` mtime 保持 2026-09-23，产品 settings 与服务进程未修改；
   未触碰 root 的 17311 / 17312 / 17313 / 8100 与 Redis db0。

   清理结果：

   | 项 | 结果 |
   | --- | --- |
   | `T-TIMEOUT`（root `astra-inject-t66mut8y`） | 正常 `RuntimeService.stop(cancel_task=True)`：`RUNNING → CANCELED`，同 Session `ses_f0ce6ebebffe5SZWUZUe2GHboJ`，Session `INTERRUPTED` / reason `aborted` |
   | `T-ACK`（root `astra-inject-bwgp2yw2`） | 同上：`RUNNING → CANCELED`，同 Session `ses_f0cdd8ccdffeBpryg2gh6gnKLh`，Session `INTERRUPTED` / reason `aborted` |
   | 保留项 | SQLite 行、Session 记录、worktree 与日志全部保留（仓库外临时目录，未提交） |
   | relay 50883 | 原进程 `finally.shutdown` 后已 0 listener；清理阶段为执行正常 stop 临时新起的 native 随后关闭 |
   | 进程清理 | 仅对自身 `astra-inject` cwd 的 8 个进程（32268, 32721, 34345, 35170, 35283, 37530, 32267, 37529）发 SIGTERM；59370 / 64000 / 50134 / 50776 / 50882 / 50883 全部 0 listener |
   | 范围外 | 未清理任何范围外服务 |

7. **本地开发态副作用**
   为真实验收在本地 SQLite 中新增 5 个验收员工、5 个验收分类与若干任务，
   隔离 Git 项目与 OpenCode 1.2.27 二进制均位于仓库外临时目录，未提交。
   `astra-01` 执行环境字段已还原。
