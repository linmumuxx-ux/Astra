# CTB Test Benchmark

训练和评估规格驱动测试设计 Skill。

- `skills/ctb-test-design`：核心测试设计与 testcase 生成。
- `skills/ctb-exercise-loop`：基于 testcase→bug_id 反馈的训练闭环。
- `benchmark/traffic_light`：第一道公开模拟题。
- `experience/bug-patterns.md`：跨题可迁移经验。

Design Skill 只能读取题目公开区；`implementation/` 仅提供本地正确运行环境，`hidden/` 仅供评测器使用，二者都不得用于测试设计。

正确环境：`cd ctb/benchmark/traffic_light && python run_correct.py`

隐藏评估：`cd ctb/benchmark/traffic_light/hidden && python evaluate.py`
