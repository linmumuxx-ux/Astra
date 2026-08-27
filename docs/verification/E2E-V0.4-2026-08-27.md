# Astra V0.4 验收报告

验收时间：2026-08-27（Asia/Shanghai）

验收结论：**本地 V0.4 功能、浏览器 E2E 与真实 OpenCode 简单闭环通过。**

## 验收环境

- macOS arm64
- Python 3.14.3（生产镜像固定 Python 3.12）
- Node.js 25.4.0
- OpenCode 1.18.23：`/opt/homebrew/bin/opencode`
- 真实验证模型：`deepseek/deepseek-v4-flash`
- Playwright Chromium

## 全量质量门禁

执行命令：

```bash
./scripts/verify.sh
```

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| 后端静态检查 | 通过 | Ruff `All checks passed` |
| 后端单元/集成测试 | 通过 | 32 passed |
| 前端类型检查 | 通过 | `vue-tsc -b` |
| 前端生产构建 | 通过 | Vite 构建完成，2305 modules transformed |
| Chromium E2E | 通过 | 9 passed，0 failed，0 skipped |

浏览器测试使用临时 SQLite、隔离端口和可控 OpenCode 测试替身，不污染本地开发数据库。机器可读结果位于 `artifacts/test-results/results.json`，HTML 报告位于 `artifacts/playwright-report/index.html`。

## 浏览器 E2E 覆盖

1. 总览显示数字办公室、真实指标、员工进展和工位快速详情。
2. 数字员工、任务中心、运行记录、待处理和配置中心均可从中文主导航访问。
3. 任务创建表单只包含业务事实和验收标准；高优先级默认人工确认。
4. “待处理”导航角标与等待人工、已挂起、待确认、执行异常及无活动聚合数量一致。
5. 员工列表提供“异常”筛选和可访问的详情链接；任务时间按 UTC API 数据正确转换为本地时间。
6. Run 列表可直接进入运行详情和关联任务。
7. 已完成任务展示结果、逐项验收、Token、Tool 和 Run 关联。
8. 员工配置只管理工作范围、长期工作环境和简单工作策略。
9. 主要页面不直接暴露英文业务状态；验收结果、证据类型、时长和用量标签均以中文呈现。

## 真实本地 OpenCode 验收

执行命令：

```bash
.venv/bin/python scripts/real_opencode_smoke.py \
  --model deepseek/deepseek-v4-flash \
  --opencode /opt/homebrew/bin/opencode
```

该脚本在仓库内创建隔离的临时员工工作空间和 SQLite 数据库，通过真实 `TaskCoordinator` 运行一项任务；成功后自动清理现场，不读取或输出模型凭据。

本次结果：

| 项目 | 结果 |
| --- | --- |
| Task 状态 | `COMPLETED` |
| Run 状态 | `PASSED` |
| OpenCode 退出码 | `0` |
| 模型 | `deepseek/deepseek-v4-flash` |
| 实际 Total Token | `32503` |
| 实际 Tool 调用 | `2` |
| OpenCode Session | 已创建并写入 Run |
| 验收文件 | 已生成，内容为 `ASTRA_V04_OPENCODE_OK` |

验收还确认：OpenCode 即使以退出码 `0` 返回，只要 stderr 出现权限请求被自动拒绝，Astra 也会将其识别为 `BLOCKED`，不会误报成功；该场景已有后端回归测试。

## 用户体验复验

- 独立 V0.4 环境中的首页、任务、员工、待处理、配置和 Run 页面均可正常加载。
- 待处理角标与页面均为 3 项演示待办。
- 数字办公室工位恢复预期边框和次要文字层级。
- 任务创建、最后活动和运行时长口径一致，不再出现 UTC 时间被当成本地时间造成的 8 小时偏差。
- 任务状态、验收状态及相关展示标签保持中文；未知枚举不再直接显示英文内部值。
- 员工返回的结构化验收结果可直接入库，旧版清晰 Markdown 验收表也能解析；只有真正缺失结论时才显示“无法确认”。
- 隔离站点浏览器控制台错误为 0。

## 未纳入本机通过结论的边界

- 当前主机没有 Docker CLI，因此没有实际构建或启动生产 Compose。
- Linux 远程 SSH/OpenCode 只有自动化回归，仍需在目标 Linux 主机验收。
- 正式 `nr_test_system` 发现与结果回填接口仍需对端提供真实契约和环境后联调。
- 管理台没有内置认证/RBAC，生产必须放在可信内网或企业认证网关之后。

## 复现顺序

```bash
./scripts/verify.sh
.venv/bin/python scripts/real_opencode_smoke.py \
  --model deepseek/deepseek-v4-flash \
  --opencode "$(command -v opencode)"
```
