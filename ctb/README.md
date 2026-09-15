# CTB Test Benchmark

训练和评估规格驱动测试设计 Skill。

- `skills/ctb-test-design`：核心测试设计与 testcase 生成。
- `skills/ctb-test-design/references/design-playbook.md`：按题目结构加载的测试设计方法，不在主 Skill 中平铺全部细节。
- `skills/ctb-test-design/references/runtime-policy.md`：FAST/BALANCED/THOROUGH 自适应执行策略。
- `skills/ctb-exercise-loop`：基于 testcase→bug_id 反馈的训练闭环。
- `tools/skill_benchmark.py`：重复运行、token/时延/稳定性采集与 baseline/candidate 晋级门禁。
- `EFFICIENCY_OPTIMIZATION.md`：持续优化方法和命令。
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

## Benchmark 评价指标

### 第一层：正确性硬门禁

1. 正确环境 PASS 率；
2. 首轮 hidden kill rate 的 `min / p50`；
3. 不允许 candidate 用更低 token/时延抵消准确率下降。

### 第二层：稳定性门禁

4. generation success rate；
5. kill rate stdev；
6. wall time 的 p95 / CV；
7. 超时、工具失败和异常退出。

### 第三层：准确率一致后的效率

8. wall time p50 / p95；
9. total token p50 / p95，并保留 input/output/cache 拆分；
10. LLM call / tool call；
11. testcase 数、`kill / testcase`；
12. 第二轮 `新增 bug / 新增 testcase` 边际收益。

正式 baseline/candidate 比较使用 `benchmark_efficiency_policy.json`。默认至少重复 5 次，p95 权重大于 p50，避免只优化平均值。

静态 Skill 体积只用于防止主 Skill/Reference 无限制膨胀，不等同于真实模型 token；真实 token 由 OpenCode JSON 事件采集。

比赛能力更看重**首轮高命中 + 稳定 + 低成本 + 反馈后快速补齐**，而不是无限堆 testcase 后达到 100%。

## Skill 自适应执行

每次执行先 Scout，再选择 `FAST / BALANCED / THOROUGH`：简单题 FAST，一般状态/边界/关系题 BALANCED，复杂冲突或高风险 GAP 未解决时 THOROUGH。调用方 profile 只是成本目标，发现高风险证据必须自动升级。

## 训练集与 Holdout

一旦某题的 hidden/mutant 被人工或 Agent 查看，并用于修改 Skill，该题即视为训练集。train 用于提炼，regression 用于防退化，holdout 只用于 candidate 冻结后的独立评测。

用于 Skill A/B 的题目应提供 `starter_test_submission.py`。Harness 每轮先生成公开 workspace，再用该冻结模板覆盖可能已经演进过的 `test_submission.py`，确保 baseline/candidate 从完全相同的起点开始；仓库内已解 testcase 可继续用于 regression，但不会泄漏到本轮 Agent 起点。

## 公开 workspace

```bash
python ctb/tools/prepare_public_workspace.py ctb/benchmark/traffic_light <workspace_dir>
python ctb/tools/prepare_public_workspace.py ctb/benchmark/smart_lock <workspace_dir>
```

## Skill 成本与稳定性评测

```bash
python ctb/tools/skill_benchmark.py run \
  --question ctb/benchmark/<holdout> \
  --skill ctb/skills/ctb-test-design \
  --model <provider/model> \
  --runs 5 \
  --output .ctb-eval/candidate

python ctb/tools/skill_benchmark.py compare \
  --baseline .ctb-eval/baseline/summary.json \
  --candidate .ctb-eval/candidate/summary.json \
  --policy ctb/benchmark_efficiency_policy.json \
  --gate
```

详细规则见 `EFFICIENCY_OPTIMIZATION.md`。
