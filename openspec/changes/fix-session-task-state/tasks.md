## 1. Session 判定

- [x] 1.1 当前轮事实、retry 与无法定位时的收敛

## 2. Task 投影与占用

- [x] 2.1 SUCCEEDED、FAILED、INTERRUPTED、UNKNOWN 的投影、确认、取消和唤醒

## 3. 可见结果

- [x] 3.1 列表、详情和办公室能区分执行中、本轮已完成、执行异常和连接异常

## 4. 验收

- [x] 4.1 补齐状态转换与 Worker 占用测试，并跑 task-platform 检查与 web build

## 5. 对账与取消复审

- [x] 5.1 取消开始后拒绝新的 send/retry，最终事务核对轮次锚点与提交预留
- [x] 5.2 已成功 Session 的快捷路径幂等修正仍在 RUNNING 的 Task
- [x] 5.3 同一轮等待原因变化时补发结果事件和 outbox，并更新进度文案
- [x] 5.4 unconfirmed 在消息恢复后重新推导；已确认完成的详情文案与待确认区分
- [x] 5.5 取消前已在途、结果未明的提交保持占用；结果明确后 abort、对账并释放 Worker
