# 首页数字办公室

本页是 Astra 已有执行状态的可删除展示层。Task 管理业务闭环，OpenCode Session 提供执行事实，RuntimeSession 只提供当前绑定和终态索引。办公室不创建任务、Session、Agent、数据库表或事件系统。

## 首页与视觉

旧首页通过六个 dashboard 聚合接口，展示概况卡片、员工列表、近期任务表格、人工事项、活动和知识模块；首页断开全局 SSE，依赖30秒轮询。仓库旧办公室与人物素材均不参与本次首页实现。

现在顶部为简短概况，中间为连续办公室，右侧为人工事项和最近12条动态，底部只有一行统计。移除旧大统计卡、近期任务表格和知识模块，保留任务中心、数字图书馆入口。

连续房间、桌椅与人物直接复用 `workbzw/ai-office-react`，将其桌/人物/椅子分层与锚点适配到 Vue DOM。人物由原始角色资源离线导出静态姿势；运行中只播放 CSS 键盘、身体微动和屏幕反馈，人工等待显示黄色提示并转向使用者。没有随机走动或自动演示。来源与离线脚本见 `frontend/THIRD_PARTY_NOTICES.md`。

员工保持后端顺序，状态变化不挪工位。桌面3列；工位区域可纵向滚动，全部员工仍在DOM中可访问。团队、状态和全局搜索用于缩小范围。头顶只显示姓名与当前动作，完整任务、职责、团队和状态放在浅色分行提示中。提示以姓名/动作定位，限制宽度与工位视口边界；参考元素滚出视口后隐藏，不遮挡筛选栏，不叠加浏览器原生 title 提示。

## 状态映射

后端只连接 `Task.current_session_id`，同时要求 Session 的 Task、员工匹配且 `superseded_by` 为空；不探测每位员工的 OpenCode Server。

| 展示状态 | 当前事实 | 动效 |
| --- | --- | --- |
| attention | Task WAITING 且有人工原因或员工 WAIT_HUMAN | 黄色提示、轻微呼吸；直接进入当前 Task Workspace |
| working | 当前 Session RUNNING、连接 CONNECTED、后端工位 working | 键盘/身体/屏幕工作动画 |
| waiting | 当前轮 WAITING/INTERRUPTED、员工暂停或连接不可用 | 静止并显示后端状态文案 |
| error | 当前 Task/Session FAILED 或员工 ERROR | 静态红色异常提示 |
| idle | 无任务、PENDING、当前轮 SUCCEEDED、已停用/离线，或状态待确认 | 静止；使用后端状态文案 |
| thinking | 展示接口支持，但目前没有可用的明确分析阶段事实 | 暂不从文字或计时猜测该状态 |

当前轮已结束而业务 Task 仍 RUNNING 时，工位必须静止。旧失败轮次不抢占新 PENDING 任务；历史失败仍在待处理列表。工作动作使用当前任务标题，避免旧进度摘要“等待启动”覆盖真实工作状态。

点击有任务的工位进入现有 `/tasks/:id`，由原任务页打开当前 Session/Workspace；无任务进入 `/employees/:id`。首页不复制问题答复或权限确认逻辑。

## 数据、动态与恢复

首页仅请求 `overview`、`employees`、`attention`、`activity` 四个原聚合接口。API 扩展当前任务绑定、人工原因和所需轻量统计；不新增独立 Office API。

App 保持一条 SSE：首页只消费连接和事件，用同一连接触发四个聚合刷新；其他页面保留原 store 刷新。350毫秒合并事件，单次刷新期间到达的事件补刷一次。重连、回前台重新取快照；前台15秒补刷弥补原生 Session 结束可能没有业务 Event 的情况。后台停止补刷和动效。

接口失败保留上一成功快照并明确标记，暂停工作动画；首次失败显示重试。只有连接正常、页面可见、员工快照已成功更新时才能播放动画。顶栏徽标复用首页 overview 的待处理计数。完成反馈仅来自新到达的 `task_completed` 事件，首次加载历史不播；动态先于员工快照返回时，待当前工位空闲后播放一次。已处理事件 id 仅保留在当前最近动态范围内。

## 范围与回滚

本次按使用者要求只覆盖桌面端，不增加手机或窄屏专用布局。

主要文件为 `DashboardView.vue`、`components/home/`、`features/home/`、dashboard聚合、App/store首页 SSE 模式与顶部徽标。还包含开源素材和对应回归测试。

删除首页组件/映射/素材并恢复原视图、首页 SSE 模式和聚合扩展即可回滚；没有数据库迁移，未修改 Task/Session/Runtime 生命周期或 workspace-ui 源码。

验收结果与截图见 `evidence/digital-office-home-20261001/README.md`。
