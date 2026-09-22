---
description: Superpowers writing-plans - turn an approved design/spec into a bite-sized implementation plan
---

使用原生 `skill` 工具加载并执行 `writing-plans` skill，然后处理下面的输入。

要求：

- 每个任务保持 2-5 分钟粒度，给出准确文件路径、完整代码或明确改动、验证步骤。
- 不要并行混改；先输出计划，再按计划执行。
- 如果输入来自 OpenSpec change，读取该 change 的 design/spec/tasks，把计划与 `tasks.md` 对齐，避免两套任务清单。

输入：$ARGUMENTS