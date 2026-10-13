# Astra 1.0 未闭环与已修问题

2026-10-13。此文件是验证问题记录，实施仍以 OpenSpec `tasks.md` 为唯一清单。以下必需能力不会从 1.0 范围移除；全部闭环前不得正式切换或宣称完成。

| 必需能力 | 当前缺口 | 验收依据 |
| --- | --- | --- |
| Task 原生执行及独立验收 | 真实启动、采集、人类及独立 Persona 验收已通；自动返工续做、Goal 跟踪、pause/stop/takeover 与未知副作用对账全链尚未通 | worker-task-execution；任务并行/恢复/旧 attempt 隔离 |
| 完整持续履职与协作 | 全部业务 MCP Tool、外部连接器、同级冲突裁决、完整多员工修复复验流程未通 | continuous-duty、team-collaboration；真实多员工验收 |
| 知识与成长 | 成熟 Wiki/Experience 服务提取、Skill 提案/Worker 验证/审批/发布/效果/回滚尚未通 | knowledge-growth；不能以 Memory 通过替代 |
| 模型 API 与资源治理 | Provider/密钥/路由/硬配额/成本指标尚未通；目前预算只门禁新增 Persona 回合，Task 工程预算预留/硬限制未接 | trusted-governance；真实成本归属与预算控制 |
| 消息完整性 | 受控附件、外部 Binding、订阅/通知偏好未接；页面明确禁用附件入口 | team-collaboration；受权引用/隔离/防循环 |
| 组织运营 | 调岗、归档责任清点、Goal 主责转让、完整绩效与预算流程未通 | digital-team-identity；在途工作不能丢失 |
| 部署和恢复 | Linux 原生 Runtime/SSH 已验证；远程 Task 工作区、公司全服务部署、Workspace UI 授权代理、全分页、内网冷构建、依赖全锁、灾备未通 | runtime 兼容与全部页面/运维门禁 |
| 正式迁移切换 | 仅只读查验既有 Linux 连接配置；未冻结/导出/导入真实历史，Session/Workspace/Knowledge/Skill/会话未逐条签收；同步 ETL MySQL 未验，旧树仍为复制来源 | one-time-0xx-migration；真实报告、停旧、单运行树 |

## 本地验证中已处理

- OpenCode 1.18.35 声明 `json_schema` 输出，但真实 Session 持久读取 HTTP 400；短 Persona 明确使用文本 JSON + 后端严格 schema 校验，无失败重提分支，见 `runtime-compatibility-report.json`。
- Memory notes 文件名 schema 补充基础文件名约束，防止模型把 `notes/` 当文件名；真实模型随后通过。
- SSE 后台刷新原先会卸载已打开的版本选择器；保留已加载内容、首次加载/失败单独处理，10 项浏览器 E2E 通过。
- MySQL 锁等待/死锁转安全 409 并要求同幂等键重试，不暴露 SQL；真实隔离 MySQL 测试通过。
- SSE 在 yield 前释放数据库 session，实时撤权后发送 `auth_revoked`，避免连接持有事务跨等待。

- 新增验收 UI 的 Element Plus Checkbox 注册和证据筛选已修复，真实浏览器逐条审核通过。
- schema 1002 新字段触发离线迁移显式映射拒绝；补充历史执行意图/权限摘要为明确未知 null，未猜测历史事实，27 项迁移回归通过。
- Persona 首次真实验收改写测试输出被拒；保持逐字/哈希校验，明确短摘录协议后通过。已知无效决策记录 FAILED、独立用量和拒绝原因，至少冷却 60 秒再判断；未知网络提交仍仅恢复原 Session。
- RadioGroup/RadioButton 的独立安装器为空操作；改为安装 ElRadio 统一注册，真实浏览器工作分类筛选通过。

## Linux 基础设施发现

旧模型中转响应经 httpx 解压后仍携带 Content-Encoding，导致原生 1.19.0 报 `Response decompression failed`；失败 Session `ses_ecc647f3dffe3mpM1TY51WPL81` 与隔离目录保留。正式提取新网关时必须修正响应体/编码头的一致性并补压缩流测试，不在新业务运行树引入旧网关 wrapper。本次 Linux Runtime 改用显式受保护的独立模型连接配置完成真实验证，不代表新模型网关已完成。
