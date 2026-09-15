# CTB Skill 持续优化与评估

## 目标函数

CTB Skill 不使用“准确率、token、时延直接加权”的单一总分。采用分层门禁：

`正确性门禁 -> 稳定性门禁 -> 成本比较 -> Promote / Hold / Reject`

原因是比赛语义明确：**准确率一致时再比较时长、token 和稳定性**。因此任何“更便宜但漏 Bug”的版本都不能被效率分抵消。

## 评估数据

每个 Skill / 模型 / profile 至少重复 5 次，记录：

- 正确环境 PASS；
- hidden kill rate 的 min / p50 / stdev；
- generation success rate；
- wall time p50 / p95 / CV；
- input / output / cache / total token p50 / p95；
- LLM call、tool call；
- testcase 数和产物 hash（只作为行为波动观测，不要求文本完全一致）。

静态 Skill 体积单独记录 `estimated_context_tokens`，只用于防止 SKILL/Reference 无限制膨胀；它不是实际模型 token。

## Promotion 规则

默认策略见 `benchmark_efficiency_policy.json`：

1. 正确环境 PASS 率必须 100%。
2. candidate 的最低 kill rate 和 p50 kill rate 不得低于 baseline。
3. generation success rate 不得下降，accuracy stdev 不得明显放大。
4. 只有前三项通过后才计算成本指数。
5. 成本指数使用 duration p50/p95 与 total token p50/p95；默认更关注 p95，避免只优化平均值。
6. 至少 5% 综合改善才 Promote；单项成本恶化超过 10% 时不 Promote。

阈值是工程默认值，不是比赛规则。获得官方评分细则后只改 policy，不改 Harness。

## 三类评测集

- **train**：可看 hidden，用于定位策略缺口和提炼经验。
- **regression**：历史训练题，只验证旧能力不退化。
- **holdout**：hidden 从未参与 Skill 修改，用于候选版本 Promote。

任何从 hidden 得到的经验一旦进入 Skill，对应题目立即从 holdout 降为 train/regression。

## Skill 自适应

`ctb-test-design` 采用 Scout -> FAST/BALANCED/THOROUGH：

- 先用低成本 Scout 判断题目风险；
- 简单题走 FAST；
- 状态/边界/副作用等自动升级 BALANCED；
- 只有复杂冲突或高风险 GAP 未解决才进入 THOROUGH；
- 预算只能消除冗余，不能跳过 P0。

这样优化的是“无效思考/读取/调用”，而不是把分析质量直接砍掉。

## 持续优化循环

每次 Skill 修改按以下顺序：

1. 形成 candidate，不覆盖当前 baseline。
2. 在 train/regression 做快速回归。
3. 在 holdout 对 baseline/candidate 各重复至少 5 次。
4. `skill_benchmark.py compare` 做 accuracy/stability gate 与成本比较。
5. 只有 `PROMOTE` 才升级 baseline；`HOLD` 保留实验；`REJECT` 回滚。
6. 对 token/time 热点做归因：重复读文档、全量 playbook、冗余 subagent、重复工具失败、低价值 P2、过长状态文件。
7. 优先删冗余或改为按需 reference；再次运行相同 eval。

不要让 Skill 自己根据单次运行结果直接改写自己。自适应发生在**单次执行策略选择**和**经过重复 Eval 后的版本晋级**两层，避免自我强化偶然结果。

## 命令

真实 OpenCode 重复评测：

```bash
python ctb/tools/skill_benchmark.py run \
  --question ctb/benchmark/<holdout> \
  --skill ctb/skills/ctb-test-design \
  --model <provider/model> \
  --runs 5 \
  --output .ctb-eval/candidate
```

比较 baseline / candidate：

```bash
python ctb/tools/skill_benchmark.py compare \
  --baseline .ctb-eval/baseline/summary.json \
  --candidate .ctb-eval/candidate/summary.json \
  --policy ctb/benchmark_efficiency_policy.json \
  --gate
```

检查 Skill 静态体积：

```bash
python ctb/tools/skill_benchmark.py footprint \
  --skill ctb/skills/ctb-test-design
```

如果需要显式压测档位，可分别加 `--profile fast|balanced|thorough`。正式成绩建议使用 `auto`，让 Skill 根据风险自行升级。
