## 1. 控制面基础

- [x] 1.1 定义数据模型、Alembic 迁移、凭据加密与 Key 摘要；只返回脱敏字段。
- [x] 1.2 实现节点/Pool/Route/Key CRUD、节点安全下线、操作审计；控制面访问随 Astra 管理台。
- [x] 1.3 实现草稿校验、版本发布、Redis 快照通知和回滚。

## 2. 数据面

- [x] 2.1 建立独立 Gateway ASGI 入口、配置加载和实例心跳。
- [x] 2.2 实现 Gateway Key 鉴权、模型路由、原子并发租约、周期额度与 least active 选节点。
- [x] 2.3 实现非流式/SSE 透明转发、严格安全重试、断开清理及结构化错误。
- [x] 2.4 实现主动健康探测、被动降级、自动摘除与恢复、熔断半开。
  - 并发租约改为每请求唯一 lease ID 的 ZSET 原子存储（Lua 内 prune/限额/获取/释放），长流周期续租，崩溃按各租约 TTL 回收。
  - 节点健康与熔断落在 Redis 运行态，Gateway 后台按节点周期执行网络/服务/真实模型/SSE 探测；数据面调度实时读运行态健康。
  - 熔断 CLOSED/OPEN/HALF_OPEN：OPEN 30 秒后只放行少量试探，成功关闭、失败重开；被动错误降级为 DEGRADED。
  - 控制面 delete_node 的活跃并发改用同一运行态事实来源（lease ZSET），弃用旧计数键。

## 3. 观测与管理台

- [x] 3.1 持久化调用日志与健康记录，提供 Token/延迟/吞吐/实例统计查询。
- [x] 3.2 新增 API 中转导航、总览、节点抽屉和详情、Pool/Route/Key/日志/版本管理页面。
- [x] 3.3 纳入统一服务脚本、部署示例与运维说明。
  - `ops/dev/astra_service.py` 在 dev/pro 以独立进程启动 `app.gateway.server:app`（默认 `127.0.0.1:8110`），统一 status/stop/restart 与 `/healthz` 就绪等待；正式模式强制校验主密钥与 Redis。
  - 新增 `deploy/systemd/astra-gateway.service`；nginx 反代 `/v1` 并关闭缓冲；根与 deploy 的 `.env.example` 补网关变量；当时的 `docs/deploy/DEPLOYMENT.md` 增加部署、运维与 OpenCode baseURL/API Key/Model 示例（该手册已删除，现行说明是 `ops/deploy/DEPLOYMENT_GUIDE.md`）。

## 4. 验证

- [x] 4.1 编写并运行控制面、数据面及 Mock Proxy 场景测试。
  - 发布改为可恢复的两阶段状态（PENDING/CURRENT/FAILED）+ 对账，不再删除不可变版本、不在结果未知时谎称旧配置生效；覆盖并发发布。
  - 真实 Redis Lua 已用临时 Redis 8.8.1 联调：提供 `ASTRA_TEST_REDIS_URL` 时 `test_redis_lua_scripts_against_real_redis` 验证租约限额原子性、续租与释放；未提供该变量时默认 skip。
- [x] 4.2 运行后端 lint/相关测试、前端 type-check/build、迁移升级及 diff 检查。

## 5. 运行态一致性修复

- [x] 5.1 健康/熔断按「节点 ID + 连接指纹」作用域隔离：草稿编辑与草稿探测不再改写已发布连接的运行态；连接变化后新配置必须重新探测；旧实例/旧版本的探测与请求结果无法把新配置判为 HEALTHY。
- [x] 5.2 运行态健康是调度唯一依据：移除启动时用发布快照播种健康，并删除 `_select_node` 的 `runtime.health(...) or node.health_state` 回退；缺失运行态一律按 UNKNOWN 处理。
- [x] 5.3 数据面后台探测仅在与草稿连接指纹一致时才更新 DB 健康投影，避免旧版本探测把草稿判为 HEALTHY。
- [x] 5.4 `NodeCreate` 默认安全态 DRAINING/DISABLED，消除缺省 ACTIVE 绕过「显式 ACTIVE 创建需 HEALTHY」的隐式通道；`ConfigLoader` 在只有 PENDING/FAILED 时返回空配置的测试补齐。

## 6. 吊销立即阻断

- [x] 6.1 Redis/进程内运行态新增跨实例、只增不减的已吊销 Key 摘要集合；就绪是同一集合内的哨兵成员（`__ready__`）而非独立键，`sync_revoked_key_digests` 用一次 `SADD` 追加摘要与哨兵、绝不整表清空。
- [x] 6.2 控制面 `revoke_key` 先写共享阻断状态再提交 DB 吊销；Redis 不可用返回结构化 503 且不谎称成功。
- [x] 6.3 数据面 `/v1/models` 与 `/v1/chat/completions` 在读取请求体与下游调度前查询共享阻断状态；Redis 不可用或就绪哨兵缺失 fail closed，已有长流不断开。
- [x] 6.4 Gateway 启动与后台周期从 DB 追加同步所有 `revoked_at` 非空摘要并写入集合内就绪哨兵，Redis 清空/重启或整集合键被淘汰后可重建阻断列表；新增 `ASTRA_GATEWAY_REVOCATION_SYNC_INTERVAL`。
- [x] 6.5 新增控制面与数据面测试：吊销未发布立即 401、跨实例共享、回滚旧版本仍拒绝、Redis 故障/哨兵缺失 503、整集合键被删除后 fail closed 并从 DB 重建；真实 Redis 用例沿用 `ASTRA_TEST_REDIS_URL` 条件。
- [x] 6.6 `is_key_revoked` 用一次原子读取同时判断同一集合内的就绪哨兵与摘要（Redis Lua / 进程内单步），哨兵缺失让该调用本身 fail closed；数据面只做一次该调用，单独的就绪查询仅用于诊断/测试。
- [x] 6.7 已吊销 Gateway Key 作为 DB 永久 tombstone：`revoke_key` 与 `_apply_snapshot` 用 Key 行锁串行化，回滚旧快照不删除其行、不清除 `revoked_at`、不重新启用；旧快照含该 Key 时回滚新快照改为 disabled+revoked 并保留当前吊销时间；普通未吊销 Key 回滚语义不变。

## 7. 删除控制面登录管理

- [x] 7.1 删除管理 Token、角色依赖与权限接口；控制面无凭据可查询和写入，审计采用固定 Astra 来源，保留 Key 自助与数据面鉴权。
- [x] 7.2 删除前端登录门禁、会话缓存、身份/退出入口和角色条件；管理页面直接加载与操作，自助用量继续校验独立 Key。
- [x] 7.3 删除管理凭据配置与生产必填校验，同步环境示例和部署说明；主密钥与 Redis 要求保持有效。
- [x] 7.4 运行后端针对性测试与静态检查、前端类型检查/构建及 Gateway E2E；按新增场景完成 OpenSpec 验证，真实环境未运行项明确记录。
  - 2026-10-08：Gateway 后端针对性 104 passed / 2 skipped；全后端 435 passed / 4 skipped；发布对账审计来源补齐后控制面 27 passed。后端 Ruff、管理台 `vue-tsc` / Vite 构建、77 个相关 Chromium E2E、OpenSpec 校验和 diff 检查通过。真实 Redis / OpenCode 与生产部署未在本轮联调，证据和场景映射见 `verification.md`。

## 8. 删除配置版本与自助用量

- [ ] 8.1 删除版本/草稿/发布/回滚/对账与自助 API、模型及会话；保留保存时校验、模型 Key 鉴权、额度和审计。
- [ ] 8.2 从配置表一致读取完整配置并周期原子刷新；覆盖保存无需发布、重启、多实例、失败重试、进行中请求隔离和连接健康隔离。
- [ ] 8.3 删除两页及导航、实例配置版本字段，保持五个管理分区与按 Key 日志查询；更新相关 E2E。
- [ ] 8.4 增加删除版本历史表的迁移并在隔离数据库验证保存配置与吊销记录保留；同步部署文档与环境配置。
- [ ] 8.5 运行针对性及扩展回归、前端类型检查/构建、管理页 E2E 和 OpenSpec 场景验证；记录真实环境未验证项。
