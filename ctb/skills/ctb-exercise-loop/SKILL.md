---
name: ctb-exercise-loop
description: CTB 练习赛迭代训练器；准备题目、调用测试设计、解析 testcase 级 Bug 命中反馈并驱动下一轮增量探索。
---

# CTB Exercise Loop

## 职责

本 Skill 不替代测试设计。它负责训练闭环，并调用 `ctb-test-design` 完成每轮实际设计。

流程：

`题目 URL -> 下载/准备本地题目 -> test-design -> 本地正确环境验证 -> 提交 -> testcase/bug 反馈 -> GAP 分析 -> 下一轮`

## 设计隔离

调用 `ctb-test-design` 前必须先生成**参赛者视图工作区**，只包含题目文档、公开接口/AW、testcase 模板及比赛允许资源；不要把 benchmark 的 `implementation/`、`hidden/`、历史答案或评测结果放进该工作区。

本仓库模拟题可使用：

```bash
python ctb/tools/prepare_public_workspace.py <question_dir> <workspace_dir>
```

Design Skill 只接收 `<workspace_dir>`。正确环境验证和隐藏评测由 Loop 在隔离区之外执行。

## 状态

每道题维护 `.ctb/session.json`，只保存必要状态：

```json
{
  "round": 1,
  "hit_bug_ids": [],
  "testcases": {},
  "attempted_points": [],
  "next_focus": []
}
```

`testcases` 记录 testcase 名、设计意图、命中 bug_id 和首次命中轮次。

## 每轮处理

1. 准备参赛者可见题目文件，并生成隔离工作区。
2. 将工作区路径、上一轮压缩状态和通用经验交给 `ctb-test-design`。
3. 将生成 testcase 回写到执行区，并确认在正确环境全部 PASS。
4. 按比赛方式提交完整 testcase 文件。
5. 解析 testcase -> bug_id 映射。
6. 标记：
   - `NEW`：首次发现新 bug。
   - `REPEAT`：仅命中已发现 bug。
   - `MISS`：未命中隐藏 bug。
7. 分析本轮真正有效的测试设计特征，并生成下一轮 `next_focus`。
8. 下一轮以增量探索为主，不重写已经有效的 testcase。

## GAP 分析原则

重点回答：

- 哪类设计首次带来了新 bug？
- 哪些 testcase 只是重复验证相同缺陷？
- 哪些规格规则已有测试，但区分度仍不足？
- 哪些测试因子/状态/组合尚未探索？
- 当前全部 testcase 可能放过哪些“错误实现形态”？

Bug ID 只是覆盖标识，不把 `bug_7` 等编号本身当作业务知识。

## 经验提炼

一道题结束后，将经验分成两层：

### 题目内状态

保留具体 testcase、bug_id、测试点，用于继续迭代该题。

### 可迁移经验

只有满足以下条件才进入通用经验库：

- 能描述触发特征，而不是复述题目答案；
- 能说明容易出现的错误实现形态；
- 能给出对应测试策略；
- 在后续题目仍可能适用；
- 至少有一个 `NEW` testcase 作为真实命中证据。

推荐格式：

```markdown
## Pattern: 多条件优先级覆盖
- 特征：多个规则同时满足，规格存在优先级或覆盖关系
- 常见错误：按代码顺序覆盖结果；高优先级条件未提前返回
- 测试策略：分别验证 A、B，再构造 A+B 同时成立的区分用例
- 证据：在练习题中产生过独立新增 Bug 命中
```

## 反哺 Design Skill

训练结束不是只写总结。对经过真实命中验证的可迁移 Pattern：

1. 先与 `experience/bug-patterns.md` 去重/合并，避免同义经验持续膨胀。
2. 只有高频或高价值 Pattern 才进入 `ctb-test-design` 的检查项。
3. 回写时只保留通用测试策略，不写题目名、具体值、bug_id 或隐藏答案。
4. 下一道新题的首轮 Design 必须能够独立使用这些经验，不依赖历史反馈。

目标是让 Loop 训练 **Design 本身**，而不是形成越来越大的题目答案库。

## 停止条件

满足任一条件即可停止：

- 达到比赛/训练轮次上限；
- 连续两轮没有新增 bug，且深挖扫描没有新的高价值测试方向；
- 已达到已知 bug 总数；
- 用户要求停止。

停止后输出：累计命中数、每轮新增数、有效测试点、长期未命中的方向和新增通用经验。
