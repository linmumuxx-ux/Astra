# 验证记录：remote-employee-provisioning

日期：2026-10-09。分支：`codex/digital-office-home`。实现前已有网关、首页等大量未提交改动，本次保留，不提交或重置它们。

## 完整性、正确性、一致性

| 维度 | 结果 |
| --- | --- |
| 完整性 | 6/6 实施项；4 个 Requirement 已实现 |
| 正确性 | 10 个 Scenario 有实现及针对性测试/真机证据 |
| 一致性 | 复用环境、网关 Key、SSH 隧道、原生 Serve；未增加 Task/Session 状态副本 |

| Requirement / Scenario | 实现与验证 |
| --- | --- |
| 从配置部署：空机器、失败重试 | `remote_install.sh`、`RemoteProvisioner._install/run`；CentOS 7 真机首次部署，依赖兼容失败后显式重试成功；版本及摘要核查 |
| 自动接入本机服务 | 全局 provider/MCP + 网关/图书馆 SSH 反向隧道；真机生成、MCP initialize/tools/list 均 HTTP 200；Serve 仅 `127.0.0.1:17302` |
| 已有配置和工程 | 真实 Node 配置合并测试：保留自定义 provider/MCP/permission、备份 0600，JSONC 拒绝覆盖；非空非 Git 仓库拒绝初始化 |
| 重复部署 | 真实 HTTP 重复部署通过；既有凭据复用测试；真实数据库只有 1 个启用且未吊销的 Astra-02 专属 Key |
| 空闲重启 | 真实 HTTP 重启后健康为 OpenCode 1.2.27；前端只调用 restart 路径 |
| 占用/原生忙碌/端口冲突 | Runtime UNKNOWN 占用、手动启动、原生 busy 拒绝、端口冲突上报测试；旧 ss 不支持 -H 的兼容处理；PID/cwd/参数归属沿用原实现 |
| 操作期间冲突 | 条件更新预留与短事务环境保护，更新/删除/检测/再维护均 409，启动拒绝；前端未保存及维护中禁用 |
| 取消/断线/超时 | 后端取消与超时关闭 SSH 并标失败测试；前端流式取消恢复控件；真实 HTTP 客户端断线后允许再次成功部署 |
| 旧轮次晚到 | 操作 ID 条件完成更新，旧结果不覆盖新模型/操作测试；环境检测最终写入同样使用 CAS |

## 实际执行的检查

- 项目插件及 OpenSpec 配置检查通过（`scripts/verify.py` 前两项）。
- 全量 Ruff：通过。
- 全量后端：447 passed、4 skipped、1 failed。失败为 `test_preflight_database_isolation::test_gateway_tables_are_registered_as_astra_tables`，旧测试仍要求已被现有网关改动移除的 `gateway_config_versions`；不重建已移除表，也不改无关网关测试。整套 `scripts/verify.py` 因此未通过，未继续其后续阶段。
- 最终针对性后端（远程部署、OpenCode Server、API、Runtime）：55 passed。
- 最终前端类型检查：Vue 与 workspace-ui TypeScript 均通过。
- 前端生产构建通过；保留现有 bundle 大小提示。
- Playwright：3 passed，覆盖部署/重启成功并刷新模型、失败重试、本地隐藏、未保存禁用、维护中锁定、流式取消恢复。
- 截图已检查：`artifacts/remote-provisioning/controls.png`，控件布局正常。
- OpenSpec change 校验通过；归档前同步主 Spec。

## 真机验收

员工 `astra-02` / Astra-02：`47.77.219.113`，工程 `/opt/astra/projects/astra-02`，CentOS 7 x86_64、glibc 2.17、内核 3.10。凭据不纳入仓库。

- Node 22.23.3、Git 2.43.7、OpenCode 1.2.27 均实际启动。
- npm registry：`https://registry.npmmirror.com`；全局配置权限 0600。
- 首次部署、HTTP 重复部署、HTTP 重启均成功。
- 员工专属中转真实模型 `deepseek-flash` 返回 `ASTRA_REMOTE_OK`（18 tokens）。
- 图书馆工具发现：`library_search`、`library_get`、`library_related`、`library_submit_experience`、`library_feedback`。
- 正式任务 `T-20261009-A4870F` 创建远程独立 worktree，原生 Session `ses_edfc2cec3ffeVLEH3OIBtx99Cc` 的 Bash exit 0，输出 `ASTRA_REMOTE_EXEC_OK`，最终助手 finish=stop。通过确认接口结束业务任务，再正常删除临时任务，未根据本地计时推断终态。
- Astra-02 最终空闲、自动领取/执行启用；保留 Astra-01。
- 本机 `.env` 已配置 HTTP MCP 并启动登记 `library-mcp`；配置变更前已备份，使用原服务管理器的条件启动方式支持后续恢复。

运维证据位于被忽略的 `.astra/evidence/remote-provisioning-20261009/`；归档仅存无敏感信息的结果说明。

## 风险与未验证边界

- Debian/Ubuntu、其他 RHEL、aarch64、非 root 分支仅代码检查，未做额外真机验收。
- 全局配置按 SSH 用户共享；不要并发部署同一用户的多个员工。完整安装有远端文件锁，单员工维护有数据库租约；工程和系统安装不做自动回滚。
- SSH 隧道随本机服务生命周期存在，正式 Runtime 连接/维护会重建；平台/网络持续不可达时远程模型与 MCP 不可用。
- 本次只验收 MCP 工具发现，未执行图书馆知识写入和完整检索业务。
- 验收脚本轮询重连期间另行确认任务，触发一次既有重连响应的 `MissingGreenlet` / 500（回滚后 ORM 实例过期）；确认和删除均成功。该并发响应问题未在本次环境部署功能中修改，不能宣称整个平台生命周期无异常。
- 全量浏览器套件未执行；本次运行了上述 3 项针对性浏览器测试。

无本次需求的 CRITICAL 遗漏；以上警告保留，主 Spec 同步后归档。
