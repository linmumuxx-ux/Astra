# Evaluator only

`hidden/` 模拟比赛评测侧，`ctb-test-design` 严禁读取。

维护者先运行：

```bash
python validate_mutants.py
python evaluate.py
```

`evaluate.py` 输出：
- `killed_count / total`
- 每个 bug_id 的 killed 状态
- 每个 testcase 命中的 bug_id 列表

这份反馈再交给 `ctb-exercise-loop` 做下一轮 GAP 分析。
