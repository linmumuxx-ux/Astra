## Why

0.xx 把员工身份与执行节点混用，不能承载 1.0 的长期职责与多用户数字团队。领域、运行树和 schema 仍从固定提交重建。产品完成定义已收成 `docs/astra-1.0/SLIM_BASELINE.md` 的一条垂直切片；原「不裁剪、全量验收后一次切换」不再是 1.0 门禁。

## What Changes

下列条目是立项时的完整重建描述。1.0 要关闭的范围以 `docs/astra-1.0/SLIM_BASELINE.md` 和 `tasks.md` 为准。正式三维首页、企业 IM、Skill 全链路、全量治理配额和公司 ETL 切换已降为 Post-1.0。

- **BREAKING**：新 `apps/api`、`apps/web`、`domains`，仅公开 `/api/v1`；移除旧业务运行入口与兼容逻辑。
- 新建员工/岗位/目标、持续 Inbox/Routine/Persona、团队 Channel、正式交接、Worker 池与独立验收。
- 后端认证注入 Principal；交集授权、Workspace Grant、具体审批、审计、预算与幂等防循环。
- 真实 API 驱动全部九类页面，Three.js 首页、SSE 恢复与内网静态资源。
- 独立旧库 ETL、对账及切换工具；复用成熟 OpenCode/证据/知识/网关实现并清除旧领域依赖。
- 全量领域/迁移/真实 Runtime/多员工/权限/恢复/浏览器/公司部署验收。

## Capabilities

### New Capabilities

- `digital-team-identity`: 多用户认证、岗位、员工、目标、生命周期。
- `continuous-duty`: 事件、关注关系、Routine、短 Persona Turn、连续记忆。
- `team-collaboration`: 长期私聊、群聊、正式交接、消息防循环与隔离。
- `worker-task-execution`: Worker 租约、任务并行、原生 Session、独立证据验收与恢复。
- `trusted-governance`: 交集授权、幂等操作、审批、审计、成本、人工接管。
- `knowledge-growth`: 原始资料/Wiki/经验/Skill 提案验证发布回滚。
- `astra-product-workspace`: 九类真实页面、轻量 3D、业务 SSE 和可访问 DOM。
- `one-time-0xx-migration`: 冻结、导出、显式映射、导入、对账、单次切换。

### Modified Capabilities

- `platform-assistant-runtime`: 移除旧单平台助手产品，改为独立员工 Persona 决策 Runtime。
- `assistant-configuration`: 移除旧助手设置，改为岗位/员工决策配置与授权。
- `digital-office-home`: 首页改为动态 3D 数字团队空间，真实状态进入长期 DM。
- `task-experience-review`: 改为员工独立验收与受控知识/Skill 成长链。
- `remote-employee-provisioning`: 执行资源改为 Worker，不再给岗位员工绑定主机。
- `project-capability-registry`: 新员工/Worker 能力与工程配置按授权加载。

## Impact

重建 Python/FastAPI/SQLAlchemy/MySQL/Celery 与 Vue3/Element Plus 应用；旧库保持冻结备份边界，正式应用不得读取旧库。保留成熟 Runtime 与工作区 UI 的选择性复用，所有复制有来源与依赖审计。1.0 范围以 `docs/astra-1.0/SLIM_BASELINE.md` 为准。Post-1.0 项见 `tasks.md`。不以规划或模拟验收宣告切片完成。
