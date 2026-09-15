# CTB Test Benchmark

训练和评估规格驱动测试设计 Skill。

- `skills/ctb-test-design`：核心测试设计与 testcase 生成。
- `skills/ctb-exercise-loop`：基于 testcase→bug_id 反馈的训练闭环。
- `benchmark/traffic_light`：第一道公开模拟题。
- `experience/bug-patterns.md`：跨题可迁移经验。

Design Skill 只能读取题目公开区；`implementation/` 仅提供本地正确运行环境，`hidden/` 仅供评测器使用，二者都不得用于测试设计。

## Traffic Light 当前结果

- Round 1：17 条 testcase，命中 17/20，85%。
- Round 2：基于反馈新增 3 条 testcase，命中 20/20，100%。
- 本轮沉淀 3 类通用经验：重复/幂等、对称反向、副作用边界，并已回写 `ctb-test-design`。

结果记录见：

- `benchmark/traffic_light/results/round-1.json`
- `benchmark/traffic_light/results/round-2.json`

## 运行

正确环境：

```bash
cd ctb/benchmark/traffic_light
python run_correct.py
```

完整本地 Benchmark：

```bash
cd ctb/benchmark/traffic_light/hidden
python run_benchmark.py
```

`run_benchmark.py` 会依次完成正确环境验证、20 个变异点校验、隐藏评估，并在题目目录生成 `benchmark_result.json` 与 `benchmark_summary.json`。

GitHub Actions 也提供 `.github/workflows/ctb-benchmark.yml`，用于环境允许时自动执行同一评测链。
