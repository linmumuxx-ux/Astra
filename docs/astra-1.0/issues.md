# Astra 1.0 未闭环与已修问题

2026-10-13。此文件是验证问题记录，实施仍以 OpenSpec `tasks.md` 为唯一清单。以下必需能力不会从 1.0 范围移除；全部闭环前不得正式切换或宣称完成。

| 必需能力 | 当前缺口 | 验收依据 |
| --- | --- | --- |
| Task 原生执行及独立验收 | 派工只有 BOUND，尚未接工程启动、采集、证据审查、返工、Goal 后续跟踪、pause/stop/takeover 与未知副作用对账全链 | worker-task-execution；任务并行/恢复/旧 attempt 隔离 |
| 完整持续履职与协作 | Task 结果 SourceEvent、全部业务 MCP Tool、外部连接器、同级冲突裁决、完整多员工修复复验流程未通 | continuous-duty、team-collaboration；真实多员工验收 |
| 知识与成长 | 成熟 Wiki/Experience 服务提取、Skill 提案/Worker 验证/审批/发布/效果/回滚尚未通 | knowledge-growth；不能以 Memory 通过替代 |
| 模型 API 与资源治理 | Provider/密钥/路由/硬配额/成本指标尚未通；目前预算只门禁新增 Persona 回合 | trusted-governance；真实成本归属与预算控制 |
| 消息完整性 | 受控附件、外部 Binding、订阅/通知偏好未接；页面明确禁用附件入口 | team-collaboration；受权引用/隔离/防循环 |
| 组织运营 | 调岗、归档责任清点、Goal 主责转让、完整绩效与预算流程未通 | digital-team-identity；在途工作不能丢失 |
| 部署和恢复 | SSH/Windows、受控 Worker 凭据解析、Workspace UI 授权代理、全分页、内网冷构建、依赖全锁、灾备未通 | runtime 兼容与全部页面/运维门禁 |
| 正式迁移切换 | 未访问真实旧库，Session/Workspace/Knowledge/Skill/会话来源未逐条签收；同步 ETL MySQL 未验，旧树仍保留作复制来源 | one-time-0xx-migration；真实报告、停旧、单运行树 |

## 本地验证中已处理

- OpenCode 1.18.35 声明 `json_schema` 输出，但真实 Session 持久读取 HTTP 400；短 Persona 明确使用文本 JSON + 后端严格 schema 校验，无失败重提分支，见 `runtime-compatibility-report.json`。
- Memory notes 文件名 schema 补充基础文件名约束，防止模型把 `notes/` 当文件名；真实模型随后通过。
- SSE 后台刷新原先会卸载已打开的版本选择器；保留已加载内容、首次加载/失败单独处理，10 项浏览器 E2E 通过。
- MySQL 锁等待/死锁转安全 409 并要求同幂等键重试，不暴露 SQL；真实隔离 MySQL 测试通过。
- SSE 在 yield 前释放数据库 session，实时撤权后发送 `auth_revoked`，避免连接持有事务跨等待。
