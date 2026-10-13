# Task 原生执行与独立验收

工程执行由 `apps/services/executions.py` 协调。`domains/runtime/service.py` 负责 Worker 容量/租约/Grant/fencing，`domains/work/review.py` 负责业务验收；原生消息、工具步骤和执行状态仍以 OpenCode Session 为准。

## 部署配置

1. 人类管理员经 `POST /api/v1/system-identities/executors` 创建指定团队 SYSTEM 身份，只获得 `runtime.execute`、`task.reconcile`。客户端生成随机凭据，只提交 SHA256；服务读取的 0600 JSON 凭据文件格式为 `{"token":"安全渠道生成的值"}`，位置由 `ASTRA_V1_EXECUTOR_CREDENTIAL_FILE` 指定。凭据有效期 24 小时，须按部署运维渠道轮换。
2. 为执行服务签发具体工程的 `task.reconcile` WorkspaceGrant。员工本人仍须拥有当前岗位/员工/工程范围交集内的 `task.dispatch` Grant，系统身份不会替员工扩大权限。审核者另须有 `task.review` Grant，且为业务主责员工或其负责人；Worker/执行系统不能自审。
3. 注册 Worker 后，通过 `POST /workers/{id}/credential` 携带 `revision` 和 `file:/绝对路径` 绑定凭据引用。文件须属于服务用户、无符号链接、仅本人可读，内容为 `{"password":"OpenCode Server 密码"}`。API/审计不显示明文或引用路径；probe 与工程连接都真实解析凭据。
4. 按 `deploy/v1/execution.example.json` 写入受控 0600 JSON 文件，由 `ASTRA_V1_EXECUTION_CONFIG` 指定。键为真实 Worker ID / project_id；工程根、worktree 根、明确基线、模型和原生权限规则全部由部署管理员确定，任务正文不能自选路径。权限以 deny-all 开始，不能追加无限制通配允许。配置哈希固定到执行绑定；变化后须先对账。
5. 独立 Celery/Beat 扫描 BOUND/RUNNING 执行并投递 `astra.v1.executions.run`，使用 `astra-v1` 队列。本机工程运行器已真实验证；工程 Celery 扫描与多任务完整并发尚未完成真实 E2E。

当前工程配置只支持 **本机** Git worktree 与 loopback OpenCode Server。公司 SSH/Windows 适配未完成，不能把远端路径当作本地目录或绕过版本检查。

## 执行与恢复事实

- 派工事务只绑定 `BOUND`/`DISPATCHED` 与租约。准备意图先持久化，再在事务外建立固定 worktree、记录基线 commit、创建独立 Task Session。
- 原生 Session 固定执行 ID、目录、用途和权限摘要；与员工 Persona 的短决策 Session 完全独立。稳定输入 ID 为 `msg` + execution UUID（去连字符）。提交意图先落库，网络回执丢失后只查询原 Session，禁止重发 prompt 或另建执行。
- 只有原生 Session 出现稳定 user 输入后才标 RUNNING；原生最终 assistant 的 parent、完成时间、finish 和整个原生 Session 树 idle/工具终态共同决定可提交。idle、事件数量、时间推测及 Worker 自述均不能完成 Task。
- 原生结果只保存最终消息/真实工具引用及真实用量。子代理仍是 OpenCode 原生 Session 树，各 Session 用量按唯一索引归属到 Task 主责员工；不复制 Transcript。
- 完成执行只释放当前有效租约并把 Task 送入 REVIEW，生成一次任务来源事件及主责 Inbox。重复投递、旧 attempt、权限/配置变化均不能回写新工作。
- 暂停/取消保存具体停止意图。撤权或停止触发当前绑定的原生 abort 请求；无论是否收到 abort 回执，槽位/资产和未知副作用保留为 RECONCILE_REQUIRED，不能伪装为已经撤销。完整人工接管及副作用对账操作链尚未接通。
- 准备结果未知（例如 Session 创建回执丢失）保留准备意图，拒绝自动重新创建。观察超时保留原绑定，恢复不再次提交。过期租约不会自动抢给新 Task。

## 独立验收与证据

工作详情逐条展示原始标准，审核者选择真实原生工具片段、引用原文并说明结论。`POST /tasks/{id}/review` 必须提供 Task 当前版本、当前 execution、全部标准索引。完成要求每条通过且有证据；返工须说明未通过项，或明确进入 WAIT_HUMAN。

提交索引包含原生 Session/Message/Part 及该工具片段的 SHA256。验收重新读取原生事实并核对完整片段哈希；即使摘录仍在输出中，提交后变化的工具片段也不能用于通过验收。历史读取会显示是否与提交索引一致，不能把变化后的输出静默替换为旧证据。

后台在数据库事务外重新读取原生 Session/子树与分页消息，验证片段确实存在、非合成、工具已完成、摘录属于工具输出。bash 验证要求明确 `exit=0`，不会把缺失退出码当成成功。再在短事务复验当前身份/Grant/主责/Task 版本/attempt，原子写 TaskReview 与业务结论。成功幂等重放仍检查当前审核权限。

完成或被取代的 1.0 执行仍可经 `GET /executions/{id}/native-evidence` 读取授权范围内的原生证据；旧 0.xx 历史只读绑定通过独立归档读取，不强行补写新身份 metadata。证据输出即时读取，页面显示长输出截断提示，不落入审计或长期消息副本。

## 验证与剩余边界

`execution-live-report.json` 记录真实 Task API→密码保护 Worker→原生读/写/测试→REVIEW→浏览器独立验收→COMPLETED，以及完成后的原生证据读取。原始测试 SHA256 未变，平台另外执行五项测试复验；真实用量来自原生事实。协议故障注入覆盖创建/提交回执丢失、撤权 abort、idle 无最终回复、伪造证据、执行身份自审、验收中途撤权。

完整 Persona 自主验收/自动返工跟踪、关联 Goal 检查、跨 Worker 续做产物、人工接管/外部副作用对账、工程 Celery 实际并发、SSH/Windows 和完整多员工真实协作仍未通过。人类浏览器审核通过不替代这些验收，整体验收标记保持 false。
