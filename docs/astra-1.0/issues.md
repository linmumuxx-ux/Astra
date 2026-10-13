# Astra 1.0 未闭环与已修问题

2026-10-13 起按 `SLIM_BASELINE.md` 重排。此文件是验证问题记录，实施仍以 OpenSpec `tasks.md` 为唯一清单。1.0 完成只看垂直切片。下表第一节是切片阻断；第二节是 post-1.0，不阻塞 1.0。

## 垂直切片阻断

分项 live 报告已经覆盖 DM 隔离、Routine 唤醒、原生执行和独立验收，但它们不是同一次切片验收。在一条真实链关闭之前，不得宣称 1.0 完成。

| 切片步骤 | 已有事实 | 仍阻断完成的部分 |
| --- | --- | --- |
| Human↔Employee DM | 持久 DM、成员隔离、引用与因果限制有测试和页面证据 | 尚未与后面五步出现在同一次验收里 |
| Inbox / Routine 唤醒 | 真实 Redis/Celery/Beat 与短 Persona 回合已通过；观察和业务动作分开提交 | 该次 Persona 验收没有创建 Task，唤醒没有接到建 Task |
| 创建 Task | 新 API 与员工页可以创建 Task，业务主责是 Employee | 需要出现在上述同一条链中 |
| Worker / OpenCode 执行 | 隔离环境与 Linux 1.19.0 上的原生执行已通过；TaskExecution 只索引证据 | 旧轮次隔离尚未和 DM、唤醒串在同一次切片里。跨主机转移不是本项阻断 |
| 独立验收 | 人类与独立员工已按原生证据逐条验收；Worker 自报完成不能闭环 | 该结论需要留在同一切片证据中，不能只用分项报告代替 |
| 一张风险写入批准卡 | 具体审批、版本复验和幂等已有测试 | 切片要求这张卡出现在同一条风险写入上。硬配额和成本看板不是本项 |
| 新路径不暴露旧入口 | 新 API、服务和 agents 的 AST 检查禁止导入 `backend.app` | `deploy/systemd/` 仍以 `/opt/astra/backend` 为工作目录，仓库仍保留 `backend/`、`frontend/`。1.0 要让新应用路径停止把它们当运行入口。删除树留到切换之后 |

## Post-1.0

| 延后能力 | 当前缺口 | 为什么不阻塞 1.0 |
| --- | --- | --- |
| 跨主机产物、Goal 跟踪、pause/stop/takeover、未知副作用总账 | 分项执行已通，这些全链未通 | 超出「Worker 执行 + 独立验收」 |
| 外部连接器、同级冲突裁决、完整多员工修复复验、全部业务 Tool | 未通 | 切片只要 DM、Inbox/Routine 和建 Task |
| Skill 提案 / 验证 / 审批 / 发布 / 观察 / 回滚，以及成熟 Wiki/Experience 提取 | 未通。Memory 通过不能代替 | 完整 Skill 产品为 post-1.0 |
| Provider、密钥、路由、硬配额、成本看板 | 未通。现有预算只阻止把未知 Persona 用量当成零 | 网关硬配额和成本看板为 post-1.0 |
| 受控附件、企业 IM Binding、订阅/通知偏好 | 未接；页面拒绝伪造附件成功 | 企业 IM 与附件为 post-1.0 |
| 调岗、归档责任清点、Goal 转让、绩效与完整预算流程 | 未通 | 组织运营全流程为 post-1.0 |
| 正式 WebGL 三维首页、全部页面同时验收、内网冷构建与全分页 | 状态驱动空间和九类页面基础交互已有证据 | 三维首页和「全部页面同时变绿」为 post-1.0 |
| 公司全量 ETL 与删除旧树 | 真实历史未冻结导入；Session/Workspace/Knowledge/Skill 未逐类签收；旧树仍是复制来源 | 一次性迁移工具保留。公司切换和删树为 post-1.0 |

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
