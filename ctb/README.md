# CTB Test Benchmark

训练和评估规格驱动测试设计 Skill。

- `skills/ctb-test-design`：核心测试设计与 testcase 生成。
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

这次得到的关键结论不是再增加三个固定 testcase，而是：**历史经验必须作为扫描规则系统展开，不能退化成单点样例。** 因此 `ctb-test-design` 已加强为对关键操作、关键状态和对称对象做小型覆盖矩阵。

注意：Smart Lock 的 `candidate/` 结果属于 Benchmark 构建阶段的迁移冒烟，不是独立模型盲测成绩。正式比较模型/Skill 版本必须按照 `benchmark/smart_lock/BLIND_RUN.md` 从纯公开 workspace 重新生成 testcase。

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

正式首轮成绩必须先冻结 testcase，再执行 hidden evaluator。
