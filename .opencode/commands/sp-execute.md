---
description: Superpowers executing-plans / subagent-driven-development - execute an approved plan task by task with reviews
---

使用原生 `skill` 工具加载并执行合适的执行 skill，然后处理下面的输入。

选择规则：

- 有子代理（task 工具）且任务基本独立：加载 `subagent-driven-development`（每个任务派发新子代理，任务后评审）。
- 无子代理工具或用户要求内联执行：加载 `executing-plans`。
- 实现任何功能或修复前，必须加载 `test-driven-development`，遵循 RED-GREEN-REFACTOR。

要求：

- 一次只推进一个任务，任务完成后评审通过再进入下一个。
- 不要跳过测试；不要在没有验证证据时声称完成。
- 与 OpenSpec 组合时，对应 change 的实现阶段以该 change 的 `tasks.md` 为准，完成后更新勾选状态，再执行 `opsx-verify`。

输入：$ARGUMENTS