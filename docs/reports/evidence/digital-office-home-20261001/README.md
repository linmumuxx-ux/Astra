# 数字办公室首页验收

日期：2026-10-01。分支：`codex/digital-office-home`。预览：<http://localhost:5173/>。

## 原实现与修改原因

开发前工作区干净；已 fetch origin，基于当时本地最新 `fix/employee-task-flow-20260930` 的 `6b8d33e` 创建独立开发分支。该提交包含当前任务流程修复；远端新发现的首页分支是它的旧祖先，未回退基线。

旧首页调用六个 dashboard 聚合接口，堆叠大统计卡、员工列表、近期任务表格、人工事项、活动和知识模块，首页停用全局 SSE，依赖30秒轮询。员工 WORKING/Task RUNNING 并不等于当前 Session 还在执行，真实数据里已有 Task RUNNING、Session SUCCEEDED 的例子。

存量办公室、角色素材和未接入的布局实现均未用于新首页。选定参考截图的房间与 `workbzw/ai-office-react` 房间一致，因此直接移植其房间、桌椅、人物、分层与锚点，适配成 Vue DOM/CSS。没有引入 React、Pixi、Spine、3D 引擎或模拟任务。

## 删除与新增

- 首页移除大统计卡、旧员工列表、近期任务表格和知识模块；不再请求首页 tasks/knowledge 聚合接口。
- 新增连续房间、三列工位、真实状态动画、明显人工提醒、团队/状态筛选、姓名/职责/任务搜索、最近12条动态、底部统计行。
- 工位只接收展示模型；业务映射负责当前 Task/Session，点击使用原 Task Workspace 或员工详情路由。
- 保留顶部导航、Element Plus 控件、浅色背景、Astra 绿色主题。
- 修复提示框长条遮挡：浅色分行内容、320px最大宽度、以姓名/动作定位、滚出工位视口隐藏；删除重复原生 title。
- 修复新完成事件先于员工快照返回时丢失 ✓ 的竞态，首次历史事件不重播。

## 状态映射

| UI 状态 | 当前事实 | 展示/跳转 |
| --- | --- | --- |
| attention | Task WAITING，存在人工原因或员工 WAIT_HUMAN | 黄色 `!`、等待你的确认；原 Task Workspace |
| working | 当前未替代 Session RUNNING、CONNECTED，后端工位 working | 键盘/屏幕/身体微动；当前任务 |
| waiting | 当前轮等待/停止、员工暂停或连接不可用 | 静止，后端状态文案 |
| error | 当前 Task/Session FAILED 或员工 ERROR | 静态红色异常；原任务处理入口 |
| idle | 无任务、PENDING、Session SUCCEEDED、停用/离线或状态待确认 | 静止；有任务进任务，无任务进员工详情 |
| thinking | 展示组件支持，但后端暂无明确分析阶段事实 | 不从输出、计时或事件数量猜测，不触发伪动画 |

聚合只连接 Task.current_session_id，检查 Task/员工一致且 Session.superseded_by 为空。旧失败任务不覆盖新 PENDING 任务；计数与工位共用后端映射。

## 修改文件

| 范围 | 文件 |
| --- | --- |
| 首页 | frontend/src/views/DashboardView.vue |
| 场景 | frontend/src/components/home/OfficeScene.vue、OfficeRoom.vue、OfficeWorkstation.vue |
| 映射与读取 | frontend/src/features/home/officePresentation.ts、useOfficeDashboard.ts |
| 原 SSE 与徽标 | frontend/src/App.vue、stores/astra.ts、layouts/MainLayout.vue |
| 聚合与类型 | services/task-platform/app/dashboard.py、frontend/src/api/types.ts |
| 素材 | frontend/public/assets/office/、frontend/THIRD_PARTY_NOTICES.md |
| 回归 | services/task-platform/tests/test_dashboard_office.py、test_api.py、frontend/e2e/digital-office.spec.ts |
| 现有 E2E 校正 | frontend/e2e/astra.spec.ts、form-help.spec.ts、task-detail-workspace.spec.ts：按既有页面更新过期断言与缺失 mock，未顺带修改核心页面 |
| 契约与文档 | 设计说明 DIGITAL_OFFICE.md 已从树中删除；openspec 的 digital-office-home capability/change、design-qa.md |

## 静态、模拟与构建验证

| 验证 | 结果 |
| --- | --- |
| dashboard 针对性 Ruff/pytest | 32 passed |
| 完整 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/verify.py` | exit 0；422 后端通过、4 跳过；193 E2E通过、15跳过；类型检查、生产构建及 workspace检查通过 |
| 最终提示框/完成竞态修正后的首页 E2E | 15 passed；含60位员工、1440/1920桌面、长文案、提示滚动隐藏、完成事件先返回、初始空态与接口失败恢复 |
| 最终 `npm run build` | exit 0；包含 vue-tsc 与 workspace构建 |
| `npm run type-check` | exit 0 |
| `git diff --check` | 通过 |

全量门禁先通过，随后按反馈修正提示和完成反馈竞态，最后重跑影响范围内15项回归及生产构建。没有把最终15项针对性回归称为第二次全量验证。既有大 bundle 提示仍存在，无新增重型依赖。

模拟用例仅在 E2E 拦截接口与 EventSource；生产页面直接接真实聚合和原 SSE，无 Mock 分支。覆盖首次进入、多个状态、任务入口、空员工/无任务、接口异常快照、刷新并发、断线恢复、后台暂停与减少动画。

## 真实环境验证

前端5173、后端8100，使用已有本地员工/空间与原 OpenCode Server。页面显示实际48位员工、8个团队；真实1440×1000及1920×1080桌面检查无横向溢出，所有人物/桌椅/房间图片加载成功，浏览器 error 日志为空。

创建一次性验收任务 `T-20261001-75F724`，员工 `verify-20260930`，绑定真实 Session `ses_f0b2ae5efffePaLvF0iJtrist7`：

1. 原生 question 触发 Task WAITING，工位黄色提醒与侧栏待处理一致；点击工位直达对应任务及原生工作台。
2. 在原生工作台答复问题，观察恢复执行；通过原有 permission 允许无文件操作的短暂 sleep，实际工位变 working，键盘 CSS 动画运行。
3. Session 执行结束、业务 Task 仍 RUNNING 时，工位显示“本轮已结束”并停止工作动画。
4. 使用原任务页“确认完成”结束业务任务，Task SUCCEEDED；工位 idle、今日完成增加、动态显示真实完成事件。验收任务已完成，没有遗留执行。
5. 刷新后恢复48位员工及真实终态；未修改已有员工配置。
6. 在真实长姓名工位上打开提示并滚动：原提示的隐藏属性变 true，新可见提示保留在办公区内，没有覆盖筛选栏。

真实 ✓ 的3.5秒窗口未单独捕获；新到完成动画及竞态由模拟 E2E 验证。真实失败注入、真实网络故障未执行，对应后端/前端回归覆盖，不能称为真实环境故障验证。

## 截图

- `real-new-office-desktop.jpg`：最终1440桌面、48位实际员工、统计与动态。
- `real-new-office-wide-desktop.jpg`：最终1920桌面。
- `real-new-office-attention.jpg`：实际人工等待，新办公室视觉。
- `real-new-office-working.jpg`：真实 Session 执行中；截图当时动作摘要较旧，最终已统一使用当前任务标题。
- `real-new-office-completed.jpg`：真实业务确认完成后 idle。
- `real-tooltip-fixed.jpg`：最终分行提示及周围筛选/工位上下文。
- 较早的 `real-attention.jpg` / `real-workspace-question.jpg` 仅记录原生确认流程，属于视觉修改前的过程证据，不代表最终首页。

## 已知限制与回滚

只验收桌面端，不适配手机或窄屏。分析阶段与跨员工协作缺少可靠现有事件，暂不虚构 thinking/协作移动。Session 终态没有业务 Event 时，原恢复索引配合前台15秒聚合补刷更新首页；不靠前端计时判定终态。接口之间仍为独立快照，局部失败提示上次快照并停止动画。

回滚首页组件、映射、素材、首页SSE模式和聚合字段即可；没有迁移、数据库表、任务系统、事件中心、WebSocket、MCP或Agent体系变更。workspace-ui源代码及其构建产物未作为本次变更交付。
