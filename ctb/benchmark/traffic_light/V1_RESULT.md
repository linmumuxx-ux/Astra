# V1 Benchmark Result

待在可执行工作区运行后由评测器写入实际结果。

基线流程：
1. `python run_correct.py`：17 条 testcase 必须全部通过。
2. `hidden/python run_benchmark.py`：验证 20 个变异点并输出命中矩阵。
3. 将命中矩阵交给 `ctb-exercise-loop`，仅针对未覆盖方向设计 V2。

禁止根据 `BUG_CATALOG.md` 人工补题后再声称为 Design V1 首轮成绩。
