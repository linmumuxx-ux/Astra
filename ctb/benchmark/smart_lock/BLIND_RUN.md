# Smart Lock 独立盲测

本题已经具备公开区和隐藏评测区。真正评估 `ctb-test-design` 版本能力时，不使用 `candidate/` 与 `results/`。

1. 创建纯公开 workspace：

```bash
python ctb/tools/prepare_public_workspace.py ctb/benchmark/smart_lock /tmp/ctb-smart-lock-public
```

2. 仅把 `/tmp/ctb-smart-lock-public` 与当前 `ctb-test-design` Skill 交给被测模型。
3. 被测模型生成 testcase 后，先在正确环境验证。
4. 冻结 testcase 文件，再由维护者执行：

```bash
python ctb/benchmark/smart_lock/hidden/evaluate.py <frozen_testcase.py>
```

5. 记录首轮命中率。不得把 `hidden/`、`implementation/`、`candidate/`、`results/` 交给 Design Skill。

`candidate/` 仅是 Benchmark 构建阶段的迁移冒烟测试，用来确认题目能够区分测试设计能力，不代表独立模型盲测成绩。
