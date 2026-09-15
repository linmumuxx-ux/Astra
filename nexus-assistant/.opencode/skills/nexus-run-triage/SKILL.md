---
name: nexus-run-triage
description: 分析 NEXUS 任务执行记录、失败、超时、丢失、待人工和异常恢复路径时使用。用于需要组合 Run、Task、Employee 等真实状态判断“发生了什么、证据是什么、下一步怎么办”的场景；单纯查看某条记录无需复杂展开。
compatibility: opencode
metadata:
  domain: run
  version: "2"
  learning: candidate-review
---

# NEXUS 执行诊断

目标是基于平台证据解释执行异常，并给出可执行的下一步。不要把相关性写成根因，也不要用某一个状态域替代另一个状态域。

## 工作流

1. **定位执行**：已知 `run_id` 用 `nexus_run_get`；看某任务历史执行用 `nexus_run_search(task_id=...)`；分析失败现场优先用 `nexus_run_failure_summary(task_id=...)`。
2. **补齐当前状态**：需要判断后续动作时，再用 `nexus_task_get` 获取最新 Task；涉及执行员工或环境时按需查 `nexus_employee_get`。
3. **分层判断**：
   - 事实层：Run 状态、退出码、failure code、执行器状态、时间、当前进展；
   - 任务层：Task 当前状态、failure reason、execution error、待人工原因；
   - 判断层：只给证据支持的原因；证据不足就明确“当前无法确定根因”。
4. **给下一步**：先说明建议，不把建议说成已经执行。用户明确要求重试、恢复、取消或重分配时，再加载 `nexus-task-ops` 进入 prepare 流程。

## 状态边界

Task、Run、Employee、执行环境是不同状态域。Run `TIMEOUT` 不代表 Task 必然 `FAILED`；Employee `WORKING` 也不能证明某个 Run 正常。

`nexus_run_failure_summary` 没有返回记录，只能说明本次查询没有匹配失败现场，不能据此断言“系统没有异常”。

## 经验复用

遇到复杂失败、重复异常或当前证据对应已知模式时，可先用 `nexus_knowledge_search(keyword="nexus-run-triage")` 查找已发布诊断经验，再读取与当前 failure code、错误现象或恢复路径直接相关的条目。

经验只能帮助选择检查顺序和解释模式；当前运行事实始终以 Tool 返回为准。如果经验与实时状态冲突，以实时状态为准。

## 自迭代

只有出现以下学习信号时，调用 `nexus_experience_submit` 形成候选经验：

- 用户明确纠正了原因判断或处理顺序；
- 某类失败经过补充证据后确认了稳定的诊断路径；
- 原建议不可行，而新的恢复路径经平台状态或后续运行结果验证有效；
- 出现可复用的“现象 → 证据 → 判断 → 处理”模式，且不是单次环境偶发问题。

提交时：

- `skill_name`：`nexus-run-triage`
- `title`：故障模式或诊断经验标题，Tool 会统一加 Skill 前缀
- `summary`：概括现象、关键证据和正确处理路径
- `content_md`：`现象 / 关键证据 / 判断方法 / 推荐处理 / 误判风险 / 适用边界`
- `tags`：可补充 failure code 和业务主题，Tool 会自动加入 Skill 标签
- `source_task_id`、`source_run_id`：有真实 ID 时填写
- `experience_data`：记录故障模式、修正点和验证结果

不要因为一次普通失败、缺失日志、网络波动或未经验证的模型推断提交经验。候选必须经图书馆审核发布后，才可作为后续稳定经验复用；提交失败不影响当前诊断。

## 常见错误

- 看到错误文本就直接宣布根因。
- 混淆 Task、Run、Employee 状态。
- 为了给出结论而编造缺失日志或调用链。
- 分析请求中擅自触发重试或恢复。
- 把一次偶发环境错误沉淀成通用规则。
