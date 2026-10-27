# API 中转控制面登录删除验证

日期：2026-10-08。范围为本 change 第 7 节：删除控制面独立登录管理，保持模型数据面与 Key 自助鉴权、密钥保护及管理业务约束。

## 完整性与契约核对

第 7 节 4/4 任务完成；本轮涉及 3 项 Requirement，新增或修改的场景均有实现和验证证据。

| 场景 | 实现证据 | 验证证据 |
| --- | --- | --- |
| 无管理凭据直接查询和写入 | `gateway_routes.py` 删除全部管理鉴权依赖；各管理页直接加载并提供操作 | `test_control_plane_crud_without_management_credentials`；节点、Pool、路由、Key、发布和回滚的后端与 E2E 用例无管理 Token |
| 删除独立管理会话 | 删除 `useGatewayAuth`、`GatewayGate`、`GatewayConnect`、前端控制面 Token 和权限接口 | Gateway 布局直接访问与刷新；登录、身份、退出入口不存在断言；所有控制面 mock 检查无 `/permissions` 请求和 Authorization |
| 生产启动不要求管理凭据 | Settings 与服务脚本删除管理凭据字段和必填校验 | `test_production_gateway_requires_master_key_and_no_management_config` 与服务脚本生产依赖测试；主密钥及 Redis 校验保留 |
| 审计来源不可由浏览器伪造 | 控制面写操作与发布对账记录 `astra/system`；历史审计模型保留 | `test_control_plane_audit_uses_astra_source_despite_forged_identity`、`test_reconcile_resolves_unknown_publish_outcome`；凭据脱敏测试 |
| Key 自助保持独立鉴权和隔离 | `require_gateway_key` 保留；自助查询按 `principal.key_id` 固定范围，只有 self 请求携带 Key | 自助两个端点拒绝缺失、未知、停用、过期、吊销 Key；Key 间日志/统计隔离；E2E 自助会话、失效清理和导航不外泄 Key |

节点安全删除、草稿校验、发布/回滚确认、吊销阻断与数据面透传没有改变；既有 Gateway 后端测试和相关页面 E2E 覆盖通过。独立只读评审发现发布对账来源遗漏，修复并复验后无未解决发现。部署示例和运维说明与新契约一致，无数据库迁移或新增身份状态。

## 实际运行的检查

- 后端：在 `services/task-platform/` 运行 `../.venv/bin/python -m pytest -q tests/test_gateway_control.py tests/test_gateway_observability.py tests/test_service_gateway.py tests/test_gateway_data_plane.py`，104 passed、2 skipped。
- 全后端：`../.venv/bin/python -m pytest -q`，435 passed、4 skipped。最后补齐发布对账来源后，重新运行 `test_gateway_control.py`，27 passed。
- 静态检查：后端 `../.venv/bin/python -m ruff check app tests` 通过；最后修改的 service 与控制面测试再次检查通过。
- 管理台：在 `frontend/` 运行 `npx vue-tsc -b`、`npx vite build` 通过；本轮未重建 `workspace-ui`。构建存在既有 chunk 大小提示，不影响构建结果。
- 浏览器：隔离 Vite 服务 `127.0.0.1:15174`，Gateway 9 个 spec 文件与 `page-layout.spec.ts` 共 77 项 Chromium 用例通过，分三次取得证据：Key/布局 10 项、其余 66 项、修正 stats 401 内联错误断言后定向复验 1 项。Astra 全局 API 与 Gateway API 均使用本地 mock；此前因未隔离全局请求导致的导航超时在补齐 mock 后消失。
- OpenSpec：`node .opencode/tools/openspec.mjs validate api-gateway`、`node tools/e2e/check_openspec_config.mjs` 通过；bootstrap 回归与 `git diff --check` 通过。

## 验证边界与风险

未配置 `ASTRA_TEST_REDIS_URL`，2 项真实 Redis 联调用例跳过；未启用 `ASTRA_REAL_OPENCODE`，2 项真实 OpenCode 用例跳过。生产部署未实际联调；没有运行包含工作区重建与全站 E2E 的 `scripts/verify.py` 整套流程。服务脚本在 Backend Ruff 配置下原有的 UP017/UP036 提示未作无关修改，排除这两项后脚本检查通过。

控制面管理接口不再提供应用内鉴权，访问范围由 Astra 的内网或统一部署入口控制。新审计来源表示 Astra 系统，不再标识经过登录验证的个人身份。回退到旧代码时需要恢复原管理凭据配置。
