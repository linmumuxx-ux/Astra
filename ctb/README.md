# CTB Test Benchmark

用于训练和评估规格驱动的测试设计 Skill。

## 目标

模拟比赛的核心机制：

- 输入仅包含题目设计文档、接口/AW 与测试模板。
- 测试设计者不可读取被测实现与隐藏 Bug。
- 本地正确环境用于验证 testcase 本身可执行且断言正确。
- 隐藏变体用于评估每条 testcase 能命中哪些 Bug。
- 练习阶段根据 testcase -> bug_id 反馈持续总结可迁移测试经验。

## 两个 Skill

- `ctb-test-design`：核心能力。读取本地题目，完成规格分析、缺陷假设、测试设计、测试代码生成和本地自检。
- `ctb-exercise-loop`：训练闭环。管理轮次、提交反馈、增量探索和经验提炼，反哺 `ctb-test-design`。

## Benchmark

首个公开模拟题位于 `benchmark/traffic_light/`，采用状态控制类问题，重点覆盖边界、状态迁移、组合条件、优先级和异常输入。

> `hidden/` 仅用于 Benchmark 评估器，执行 `ctb-test-design` 时必须禁止读取。
