# Evaluator only

本目录模拟比赛评测侧，Design Skill 禁止读取。

维护者运行 `python run_benchmark.py`，检查 20 个变异点并执行隐藏评估。正确实现验证在题目根目录运行 `python run_correct.py`。

评估输出每个 bug_id 的状态和 testcase 到 bug_id 的映射，供 exercise-loop 做下一轮 GAP 分析。
