---
name: ctb-exercise-loop
description: CTB 练习赛迭代训练器；隔离公开题目、调用 ctb-test-design、解析 testcase→bug_id 反馈，并用结构化 GAP 驱动下一轮增量探索。
---

# CTB Exercise Loop

## 职责

本 Skill 不直接设计 testcase。它负责训练闭环，并调用 `ctb-test-design` 完成每轮设计。

流程：

`公开题目 -> 隔离 workspace -> test-design -> 正确环境验证 -> 提交 -> testcase/bug 反馈 -> GAP 更新 -> 下一轮`

## 硬隔离

调用 `ctb-test-design` 前必须生成参赛者视图，只包含题目文档、公开接口/AW、testcase 模板和比赛允许资源。

禁止把 `implementation/`、`hidden/`、mutant、历史答案、candidate、评测结果交给 Design Skill。

本仓库模拟题：

```bash
python ctb/tools/prepare_public_workspace.py <question_dir> <workspace_dir>
```

正确实现验证和隐藏评测只能由 Loop 在隔离区之外执行。

## 会话状态

每题维护 `.ctb/session.json`：

```json
{
  "round": 1,
  "hit_bug_ids": [],
  "testcases": {
    "test_xxx": {"test_point": "T01", "bug_ids": [], "first_new_round": null}
  },
  "new_bug_count_by_round": [],
  "next_focus": []
}
```

测试设计本身由公开 workspace 中的 `.ctb/design.json` 维护。Loop 不再复制一份长测试分析，避免状态漂移。

## 每轮处理

1. 生成全新的公开 workspace。
2. 将公开 workspace、上一轮 `session.json`、`design.json` 和通用经验交给 `ctb-test-design`。
3. Design 只新增新的高价值测试维度，不重写已经有效的 testcase。
4. 将 testcase 回写执行区，在正确环境全部验证通过。
5. 冻结本轮 testcase 后再提交/评测。
6. 解析 testcase -> bug_id 映射。
7. 对 testcase 标记：
   - `NEW`：本轮首次发现至少一个新 bug；
   - `REPEAT`：只命中已经发现的 bug；
   - `MISS`：未命中隐藏 bug。
8. 更新 `session.json` 和公开区 `.ctb/design.json` 中测试点状态。
9. 只从未探索的**规格维度**生成 `next_focus`，进入下一轮。

## GAP 分析

不要问“bug_14 可能是什么”，而要问：

- 哪些规格点只有 happy path？
- 哪些规则只测了一个对象/一个方向/一个状态？
- 哪些边界只测了边界点，没有前后值？
- 哪些 testcase 只检查主结果，没有检查副作用范围？
- 哪些重复操作、时序、非法输入没有验证状态原子性？
- 哪些 `REPEAT` testcase 实际验证了相同缺陷假设？
- 当前全部 testcase 通过时，还能构造什么明显错误实现？

下一轮必须说明新增的是哪个维度：`状态 / 条件 / 边界 / 对象 / 顺序 / 时序 / 副作用 / 可观察关系`。

仅更换普通输入数据不算新方向。

## 用结果评价 testcase，而不是只看总命中数

每轮至少记录：

- 本轮 testcase 总数；
- 本轮新增 testcase 数；
- 新增 bug 数；
- 产生 NEW 的 testcase；
- 仅 REPEAT/MISS 的 testcase；
- `新增 bug / 新增 testcase` 的边际收益。

高价值 testcase 的共同特征用于改进 Design；低收益 testcase 用于识别冗余策略。

不要为了追求单轮 testcase 数量增加低区分度用例。

## 经验提炼

经验分两层：

### 题目内经验

保留具体 testcase、测试点、bug_id，只用于该题后续迭代。

### 可迁移经验

只记录：

- 触发特征；
- 常见错误实现；
- 测试策略；
- 真实 NEW 命中证据。

经验先进入 `experience/bug-patterns.md`，但**不能因为一道题命中一次就直接膨胀核心 Skill**。

只有满足以下任一条件，才提升为 `ctb-test-design` 默认扫描规则：

1. 在至少两道结构不同的题目中都产生过独立 NEW 命中；
2. 属于成熟通用测试原理，并在独立盲测中证明能提高首轮效果。

这样避免把 Benchmark 答案训练进 Skill。

## Benchmark 污染规则

一旦某道题的 hidden/mutant 被用于分析或反哺 Skill，该题就属于**训练集**，不能再用它声明新版 Skill 的独立盲测成绩。

新版能力必须使用未参与经验提炼的新题做 holdout 验证。

## 停止条件

满足任一条件即可停止：

- 达到比赛/训练轮次上限；
- 已达到已知 bug 总数；
- 连续两轮没有新增 bug，且 `design.json` 不再存在高价值 P0/P1 GAP；
- 新增 testcase 的边际收益持续接近 0，且反例扫描没有新方向；
- 用户要求停止。

停止后只输出：累计命中数、每轮新增数、有效测试点、长期未覆盖方向、新增候选经验。
