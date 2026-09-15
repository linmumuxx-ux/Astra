# CTB Test Benchmark

训练和评估规格驱动测试设计 Skill。

- `skills/ctb-test-design`：核心测试设计与 testcase 生成。
- `skills/ctb-test-design/references/design-playbook.md`：按题目结构加载的测试设计方法，不在主 Skill 中平铺全部细节。
- `skills/ctb-exercise-loop`：基于 testcase→bug_id 反馈的训练闭环。
- `benchmark/traffic_light`：第一道状态/优先级模拟题。
- `benchmark/smart_lock`：第二道安全锁定/双实例/计时模拟题。
- `experience/bug-patterns.md`：跨题可迁移经验。

Design Skill 只能读取公开区；`implementation/`、`hidden/`、`candidate/`、`results/` 都不得用于正式盲测设计。

## 当前进展

### Traffic Light

- Round 1：17 条 testcase，17/20，85%。
- Round 2：基于 testcase→bug_id 反馈新增 3 条，20/20，100%。
- 沉淀：重复/幂等、对称反向、副作用边界。

### Smart Lock

已构建第二道不同业务形态 Benchmark，包含 20 个隐藏变异。

构建阶段迁移冒烟：

- Round 1：按公开规格 + Traffic Light 三类经验设计 20 条 testcase，17/20。
- Round 2：针对未覆盖规格 GAP 新增 3 条，20/20。

关键结论：历史经验必须作为扫描规则展开，不能退化成固定 testcase；同时扫描结果必须经过风险、可观察性和区分度排序，否则会快速膨胀 testcase。

Smart Lock 的 `candidate/` 和 `results/` 属于 Benchmark 构建/训练数据，不是新版 Skill 的独立盲测成绩。

## 设计状态

`ctb-test-design` 在公开 workspace 中维护：

- `.ctb/design.json`：规格点、缺陷假设、测试点、优先级和 GAP；
- `ctb_design_summary.md`：给人看的简短摘要。

`ctb-exercise-loop` 维护：

- `.ctb/session.json`：轮次、testcase→bug_id、新增 Bug 和下一轮关注点。

设计状态与评测状态分离，避免 hidden 反馈进入公开规格模型。

## Benchmark 评价指标

不要只看最终 kill rate。每个 Skill/模型版本至少记录：

1. 正确环境 PASS 率；
2. 首轮 kill rate；
3. testcase 数量；
4. `kill / testcase` 区分效率；
5. 第二轮新增 testcase 数与新增 bug 数；
6. `新增 bug / 新增 testcase` 边际收益；
7. 连续无新增时仍存在的规格 GAP。

比赛能力更看重**首轮高命中 + testcase 精简 + 反馈后快速补齐**，而不是无限堆 testcase 后达到 100%。

## 训练集与 Holdout

一旦某题的 hidden/mutant 被人工或 Agent 查看，并用于修改 Skill，该题即视为训练集。

- 训练集：可用于定位方法缺口、提炼经验、回归旧能力；
- holdout：hidden 从未参与 Skill 设计，只用于新版首次冻结后的独立评测。

新版 Skill 不允许继续用训练集成绩声明“盲测提升”。至少需要一道结构不同的新 holdout 题验证迁移能力。

## 公开 workspace

```bash
python ctb/tools/prepare_public_workspace.py ctb/benchmark/traffic_light <workspace_dir>
python ctb/tools/prepare_public_workspace.py ctb/benchmark/smart_lock <workspace_dir>
```

只把生成的 `<workspace_dir>` 交给 `ctb-test-design`。

## 本地评测

Traffic Light：

```bash
cd ctb/benchmark/traffic_light/hidden
python run_benchmark.py
python replay_rounds.py
```

Smart Lock：

```bash
python ctb/benchmark/smart_lock/hidden/validate_mutants.py
python ctb/benchmark/smart_lock/hidden/evaluate.py <frozen_testcase.py>
```

正式评测必须先冻结 testcase，再执行 hidden evaluator。
