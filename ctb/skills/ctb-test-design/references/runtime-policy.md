# CTB Runtime Policy

目标只有一个：**准确率不退化的前提下，减少无效读取、无效推理、重复工具调用和低价值 testcase。**

## 1. 运行档位

Skill 每次先做一次轻量 Scout，再选择档位；调用方显式传入 `FAST / BALANCED / THOROUGH` 时，仍允许因高风险证据向上升级，但不能为了省成本强行降级。

### FAST

适用于规则少、状态简单、公开接口直接、没有明显文档冲突的题目。

只做：

- 提取高风险规格点；
- P0 缺陷假设；
- 最小区分 testcase；
- 一次反例扫描；
- 正确环境验证由外层 Loop 完成。

不做全量 playbook 展开，不启用 subagent，不重复读取完整文档。

### BALANCED

默认档。适用于一般状态机、多条件、边界、对象关系题。

在 FAST 基础上补：

- 触发到的专项 playbook；
- P1 高价值 GAP；
- 一次关系/副作用/状态反推；
- 必要的确定性脚本计算或组合枚举。

### THOROUGH

仅在出现高风险证据时使用，例如：

- 多份公开文档存在冲突/歧义；
- 多层状态机、计时、并发/批量语义；
- 多对象对称关系复杂；
- 结构化响应存在多级派生关系；
- FAST/BALANCED 后仍有未解释的 P0/P1 GAP；
- 反馈轮持续 MISS 且不是普通数据重复。

THOROUGH 也不是“全量穷举”。仍只展开能提高区分度的维度。

## 2. 自动升级规则

Scout 后只要满足任一条件，至少进入 BALANCED：

- 存在状态迁移、时序、边界前后关系；
- 一个动作可能修改多个对象/字段；
- 有非法输入且要求原子性；
- 有汇总字段与明细字段关系；
- 规格点之间存在优先级、覆盖或互斥关系。

BALANCED 后若仍存在未解决的高风险规格点或互相矛盾的公开证据，再进入 THOROUGH。

**不得因为 token/time 预算接近上限而跳过尚未解决的 P0。** 成本预算是减少冗余的约束，不是牺牲正确性的理由。

## 3. Token / 时延优化动作

优先做确定性优化，而不是压缩必要分析：

1. 文档只做一次结构扫描；后续按标题/关键词定点读取，不整篇重复读。
2. `design-playbook.md` 按触发特征加载，不默认全读全展开。
3. `.ctb/design.json` 只存决策状态，不复制需求原文和长推理。
4. 相同 setup、相同缺陷假设合并断言；不同意图不强行合并。
5. 组合、边界枚举、重复关系检查优先用确定性脚本，不让 LLM 手工反复枚举。
6. FAST/BALANCED 默认单 Agent；只有 THOROUGH 且能拆成互相独立的规格簇时才允许 subagent，并要求返回短结构化结果。
7. 已确认的事实、AW 语义、测试点不重复解释；下一轮只处理 GAP。
8. 工具失败先判断是否可重试；相同失败命令不得无差别连续重复。

## 4. 停止 / 继续判据

允许停止必须同时满足：

- 所有 P0 已映射到 testcase 或明确为不可直接观察；
- 没有未解决的高风险规格冲突；
- 反例扫描没有产生新的 P0；
- 新增 testcase 只能带来同类数据重复或低区分度 P2。

否则继续或升级档位。

## 5. 自适应状态

在 `.ctb/design.json` 增加简短 runtime 字段：

```json
{
  "runtime": {
    "profile": "BALANCED",
    "escalated_from": "FAST",
    "escalation_reasons": ["state_transition", "side_effect"],
    "unresolved_high_risk": 0
  }
}
```

不记录 chain-of-thought，不记录长日志。外部 Benchmark Harness 负责记录真实 wall time、token、LLM/tool calls 和多次运行波动。
