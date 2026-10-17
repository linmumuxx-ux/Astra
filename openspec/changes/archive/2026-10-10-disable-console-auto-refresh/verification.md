# 关闭管理台自动刷新验证

日期：2026-10-10。代码位于 `codex/astra-updates-20261010`，本变更未提交。

## 原因与结论

代码确认存在全局 SSE 触发重读、首页 15 秒轮询、知识服务 10 秒轮询、网关总览 30 秒轮询；任务详情会对每条相关 SSE 并发读取任务、绑定和仓库。上述行为存在请求堆积风险，但本次没有生产卡死的性能录制，不能认定其为唯一根因。

已移除这些管理台自动请求，保留页面进入、用户筛选、手动刷新与操作后更新；首页展示手动模式及快照时间，持续工作动画停止。全局快照和任务详情刷新复用在途请求，首页不再排队补刷，任务详情刷新中禁用控制操作，避免旧读取覆盖操作结果。助手和内嵌工作区源代码未修改。

## 完整性、正确性与一致性

4/4 实施任务完成，4 项新增/修改 Requirement 已核对；方案与实现一致，无阻断项。

| 场景 | 证据 |
| --- | --- |
| 页面闲置及切回前台 | `console-refresh.spec.ts` 覆盖任务、员工、待处理；`digital-office.spec.ts` 覆盖首页事件、断线恢复、可见性；`library-service.spec.ts` 与 `gateway-overview.spec.ts` 跨过原轮询周期后请求数不变 |
| 业务事件不触发重读 | 首页注入事件及连接状态后无附加请求；各页面断言不连接 `/api/events/stream`；详情闲置时不重读任务、绑定和仓库 |
| 手动更新、失败重试、防重入 | 任务/员工/待处理只请求一批五个接口；首页重复点击不排队；详情首次失败可只读重试、重复点击不叠加、历史 Session 保持；首页和网关失败后重试恢复 |
| 操作成功与人工介入 | 任务详情现有人工确认、重连、未确认输入核对测试通过；列表操作与确认回归通过 |
| 当前执行快照及旧轮隔离 | 首页当前 Session 状态、结束及暂停状态、静态动画测试通过；详情当前/历史 Session 切换及跨任务隔离通过 |
| 多员工、动态反馈及减少动效 | 团队/搜索/状态筛选、60 人布局、手动获取新完成动态的短暂反馈及减少动态测试通过 |
| 助手与执行流 | 静态确认助手 SSE 与独立 OpenCode iframe 未移除；任务工作区用受控 iframe 验证，真实模型回复、权限流及生产负载未验证 |

## 实际运行

- `npm run type-check`：通过，包含管理台 `vue-tsc -b` 及现有 workspace-ui 类型检查。
- 管理台 `./node_modules/.bin/vue-tsc -b && ./node_modules/.bin/vite build`：通过。构建日志为 `artifacts/console-refresh-build.log`；仍有大于 500 kB 的 chunk 提示。
- `E2E_BASE_URL=http://127.0.0.1:15741 npm run test:e2e -- e2e/digital-office.spec.ts e2e/task-detail-workspace.spec.ts e2e/task-list-actions.spec.ts e2e/library-service.spec.ts e2e/gateway-overview.spec.ts e2e/console-refresh.spec.ts e2e/task-diff-race.spec.ts`：43 通过、5 跳过、0 失败（35.4 秒）。测试全部使用隔离 mock；Git 竞态 5 项因缺少 `ASTRA_DIFF_RACE_TASK` 跳过。
- `git diff --check`、OpenSpec change 校验：通过。
- 未运行 `python scripts/verify.py` 全量后端门禁；本次没有后端修改，验证聚焦管理台及相关浏览器场景。

## 风险与部署

- 任务状态及通知数量是快照，需要用户手动刷新。已有标签页必须重新加载才能停止旧脚本中的自动刷新；本次没有重启真实服务。
- 生产卡死是否完全消失、真实模型和大并发请求下的性能仍需真实环境验证；这不阻断关闭管理台自动刷新的实现交付。
- 首次运行 `npm run build` 时现有脚本连带重建了工作台 `web/nexus/public/opencode-workspace/1.18.33/` 未跟踪静态产物，该目录在工作开始前已存在；父构建已中断，最终管理台构建改为独立入口。未编辑 workspace-ui 源码，不清理或覆盖其他并行开发改动。

主规范已同步 `digital-office-home` 与 `console-data-refresh`。
