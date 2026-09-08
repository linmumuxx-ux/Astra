# AGENTS.md

## 项目范围

Astra 负责长期任务的分配、执行、状态跟踪、人工介入和异常恢复。

平台管理 Task、Run、Employee 和 Runtime 状态。  
任务具体怎么执行，由对应数字员工自己处理。

不要在 Astra 中增加 Agent 内部步骤、Skill、Tool 或工作流编排能力。

## Runtime

正式运行方式为 **OpenCode Server / Session / Event**。  
`opencode run` 只作为独立的 CLI fallback。

修改 Runtime 相关代码前，先理清：

```text
Task → Run → Employee → Worker → OpenCode Session
```

注意：

- Task、Run、Employee、Session 状态要保持一致。
- 不要根据时间戳、日志、事件数量或前端状态反推 Runtime 状态。
- Runtime 展示以 `backend/app/runtime/presentation.py` 为准。
- 修改生命周期时，要同时考虑失败、取消、超时、重试、重启、心跳丢失和恢复。
- 优先解决状态流转问题，不要靠 fallback 兜底。

## 数据兼容

历史异常数据优先通过 **Alembic migration、backfill 或一次性修复脚本**处理。

不要为了兼容旧数据长期保留：

- 新旧字段同时判断；
- 多层 fallback；
- 重复状态映射；
- 对异常历史数据的猜测处理。

能一次迁移的数据，就不要把兼容逻辑留在长期运行代码里。

## 修改要求

- 优先复用现有实现，能收敛就不要再加一套。
- 同一状态或业务规则不要在多个地方重复实现。
- 不顺手修改与当前任务无关的代码。
- 不覆盖用户已有修改。

## 验证

先跑与本次改动最相关的检查，再根据影响范围扩大。

```bash
# backend
pytest tests/<相关测试>
ruff check app tests

# frontend
npm run type-check
npm run build
```

涉及核心 Runtime 或主要用户流程时，再运行对应 E2E。

完成前检查 `git diff`，确认没有无关修改、调试代码和多余兼容逻辑。

最终说明：

**问题原因 → 修改内容 → 验证结果 → 剩余风险**
