# delete-gateway-keys 验证

## 原因与改动

原页面仅能吊销，Key 记录仍在管理列表。新增独立删除按钮和确认、DELETE 删除接口，吊销改为 POST `/revoke`；数据库通过 `deleted_at` 持久移除列表记录，保留摘要、吊销时间、调用与审计。远程员工部署查找旧 Key 时排除已删除记录。

迁移顺延为 `0034_gateway_key_deletion`，接在同一工作区已有的 `0033_employee_character` 后，保持唯一 head。

## 完整性、正确性与一致性

3 项 Requirement、10 个 Scenario 均有代码和验证覆盖，沿用现有确认框、主题和共享阻断，不引入并行状态源。

| 场景 | 实现与证据 |
| --- | --- |
| 确认删除、刷新保持、三类状态可删除 | `GatewayKeys.vue` 的 `removeKey`、`gatewayApi.deleteKey`；Key E2E 删除用例；后端三种状态参数化测试 |
| 取消删除 | Key E2E 确认取消后无删除请求、保留列表 |
| 失败重试 | Key E2E 503 后重试；后端 `test_delete_key_fails_closed_and_can_retry` |
| 末页删除修正 | Key E2E 删除第二页两条记录后回到第一页、计数为 10 |
| 已删除不可修改 | 后端删除后 PATCH、POST revoke 和重复 DELETE 均返回 404 |
| 旧配置中的启用 Key 立即失效 | 后端保留删除前配置，删除后真实 ASGI `/v1/models` 返回 401 `KEY_DISABLED` |
| 已吊销删除保留时间与历史 | 后端参数化测试核对原吊销时间、历史调用、创建及删除审计，审计不含原文或摘要 |
| 共享状态不可用 | 后端模拟运行态不可达，503 后没有吊销／删除标记和删除审计 |
| 共享状态重建 | 后端以全新运行态调用数据面持久摘要同步，已删除 Key 仍被阻断 |
| 独立吊销 | 既有吊销后端与 E2E 改用 POST，吊销后记录仍在列表 |

未发现阻止归档的实现或契约缺口。

## 已执行验证

- Ruff：本次修改的后端源文件、测试与迁移检查通过。
- Gateway 控制、配置、数据面、观测、迁移及远程部署回归：116 passed、2 skipped。加强旧缓存请求拒绝断言后控制面再次验证 43 passed；迁移顺延后再次验证 2 passed。
- 隔离 SQLite 迁移：已有 Key 数据不变，新删除标记为 NULL；`upgrade head` 成功，降级后摘要和吊销信息保留。`alembic heads` 确认唯一 head 为 `0034_gateway_key_deletion`。
- 前端 `npx vue-tsc -b` 通过；`npx vite build` 通过，现有大 chunk 提示仍在。
- Key 管理与 Gateway 布局 Chromium E2E：13 passed；接口均为本地 mock。
- 桌面列表截图检查：删除图标完整位于固定操作列内。
- `git diff --check` 和 OpenSpec change 校验通过。

## 风险与未验证范围

未执行仓库全量 `scripts/verify.py`、真实 MySQL 迁移及生产部署验证；未提供真实 Redis 测试环境，两个 Redis Lua 用例跳过。API Key 删除／吊销即时失效与重建使用真实 SQLite 和进程内运行态验证。

当前默认本地数据库仍在 `0031_api_gateway_control`，未修改其 schema 或删除真实 Key。上线需先备份并迁移至最新；其中既有 `0032_gateway_saved_config` 会删除旧配置版本历史。前后端需同时升级，旧 DELETE 调用现在表示删除；仅吊销应改为 POST `/revoke`。
