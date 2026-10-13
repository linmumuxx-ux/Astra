# Astra 1.0 正式页面与验证边界

实现位置：`apps/web`。基线为 `docs/Astra_1.0/Astra_1.0_全新架构与产品交互设计.md`，空间布局参考同包 HTML；页面中无演示数据、模拟回复或随机业务状态。所有展示来自新 `/api/v1`，真实后端缺少的能力明确显示限制。

## 页面清单

| 页面 | 路由 | 真实 API 与操作 | 交互截图 |
| --- | --- | --- | --- |
| 数字空间 | `/space` | 员工 / Task / Goal / Human Inbox / 审计快照；员工 DOM 热点进入长期 DM；本地 Three.js 场景；二维与减少动态开关 | [space.png](evidence/space.png) |
| 员工工作空间 | `/employees/:id` | 创建或恢复当前 Human 与员工的独立 DM；消息、引用、@；工作、目标、计划、Routine、Git Memory 编辑/历史 diff、Inbox 投递/观察/处理与原生 Turn；暂停 / 恢复 / 归档；新增目标、Task 和 Routine | [employee.png](evidence/employee.png)、[Memory](evidence/employee-memory.png)、[Inbox](evidence/employee-inbox.png) |
| 团队 Channel | `/channels?channel=<id>` | 当前身份有权访问的 Channel；持久消息、引用回复、@ 员工；关联工作和正式交接记录；创建 Group | [channels.png](evidence/channels.png) |
| 工作中心与详情 | `/tasks`、`/tasks/:id` | 筛选真实 Task；目标、原始验收标准、业务主责、结果与证据索引；暂停 / 恢复 / 取消 / 返工、正式交接；原生执行诊断与后端提供的 Workspace URL | [tasks.png](evidence/tasks.png) |
| 待人决策 | `/attention` | Human Inbox 分类、具体操作参数、作用域、目标与策略版本、到期时间；批准 / 拒绝 / 修改要求；真实结果与处理记录 | [attention.png](evidence/attention.png) |
| 组织与员工 | `/organization` | 建团队、岗位、独立员工与目标；版本化调整岗位、员工范围 / 权限 / 预算及目标；员工生命周期由工作空间管理；人员身份、团队成员、工程授权及撤销 | [organization.png](evidence/organization.png) |
| 数字图书馆 / Skill | `/library` | 来源资料、Wiki、Experience、Skill；检索、新建、版本化编辑、来源引用、版本比较与提案记录；个人 Memory 按员工单独进入；历史归档授权读取与哈希校验 | [library.png](evidence/library.png) |
| Worker / API | `/resources` | 注册 Worker、真实健康与版本、工程边界 / 能力 / 并发、租约、资源指标；API 网关未接入状态明确展示 | [resources.png](evidence/resources.png) |
| 履职治理 | `/governance` | 服务端指标、主体与业务引用审计、授权规则、员工决策 / 执行预算用量、Routine 观测 | [governance.png](evidence/governance.png) |

## 通用交互契约

- 凭据从登录输入，经 `Authorization: Bearer` 发送，只保存于浏览器当前会话；不接受页面传入操作身份，不在 URL、日志或截图打印凭据。
- 所有写入携带 UUID `Idempotency-Key`；网络错误重试保留同一业务请求的 key。编辑携带当前 `revision`，版本冲突交给后端明确拒绝与刷新。
- REST 与 SSE 共同遵循当前认证与业务权限。SSE 使用带认证的 `fetch`，解析增量帧并保存 `seq`，断线指数退避；网络恢复后保留游标并重新读取权威快照，不从事件数量、前端时间或动画推断 Runtime 终态。
- SSE `auth_revoked` 清除会话凭据；403 内容显示权限不足，不保留旧授权数据。列表和详情提供加载、空数据、异常、重试、网络离线与实时重连反馈。
- Three.js 只表现空间和根据真实生命周期选择的视觉颜色；环境动态不宣称员工正在思考或执行。WebGL 不可用时自动使用二维 DOM 员工空间。所有业务动作在可访问的 DOM / Element Plus 组件中完成。

## 验证方法与限制

`apps/web/e2e/run-real.mjs` 在一次性新 schema 上启动真实 API 与真实 Web，使用已签发管理员和无资源权限人类身份执行浏览器操作；没有请求拦截或前端数据注入。测试夹具通过后端创建真实业务对象，截图仅证明隔离验收环境中相应页面与操作。

自动化覆盖：数字空间入口、二维切换、长期 DM 发送与刷新持久化、认证写入幂等头、离线与 SSE 重连、Task 暂停、正式交接提案、具体人工批准与最终 Task 状态、组织员工创建、人员/团队/工程授权撤销、Git Memory 保存/刷新/diff、Inbox、九类页面读取、真实 403、手机端 DOM 布局。具体执行结果在全量验收报告记录；本页不以测试定义代替执行证据。

以下仍依赖完整后端及真实公司环境验收，不能据页面或测试夹具宣布完成：多员工真实工程协作与完整异常闭环、真实 Worker 工程执行及独立证据验收、原生 Workspace 代理与接管、Skill 验证审批发布回滚、附件上传存储、网关 Provider / 密钥 / 配额管理、公司网络与 Linux / Windows 部署、原有生产历史迁移对账。当前未接入能力没有伪造的“成功”操作入口。
