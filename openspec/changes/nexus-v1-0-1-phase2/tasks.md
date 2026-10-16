## 1. 差异分析

- [x] 1.1 对照 Phase 1 与 `origin/codex/astra-updates-20261010`（`05dd7314`），把简报第二节的九块能力写入 `design.md` 的复用清单
  - 完成标准：每一块都有直接复用、小范围适配、需要重新实现、不再需要，并写明历史文件路径
  - 验证：本文件与 `design.md` 一致；未改 `services/task-platform/`、`frontend/`、`nexus/` 业务代码

## 2. 数据关系与迁移方案

- [x] 2.1 写入 Task、责任员工、Worker、OpenCode Session 的字段关系和迁移顺序
  - 完成标准：`design.md` 说明身份拆分、调度入口、状态机保持原服务、以及不把 `domains/` 当作实现来源
- [x] 2.2 写入 Task MCP、Task Skill 在 AgentScope 2.0.10 的注册方式，outbox 加 inbox/wakeup 的投递，以及 OpenCode 默认模型
  - 完成标准：写明工具从哪次组装进入会话、Skill 按 agent 分区安装、投递与任务事件同一事务、重复投递不二次改状态；默认模型 id 为 `deepseek-flash`，配置值为 `deepseek/deepseek-flash`
  - 验证：`node .opencode/tools/openspec.mjs validate nexus-v1-0-1-phase2 --strict`

## 3. 确认门禁

- [x] 3.1 在 `design.md` 的待确认项得到用户答复之前，不开始迁移代码
  - 完成标准：用户对 D1–D10 的答复已记入本 change；未答复的项没有对应的业务代码
  - 验证：`git diff` 相对本方案提交，在答复前不含 `services/task-platform/` 或 `nexus/` 的功能改动

## 4. 后续实现（本轮不执行）

- [x] 4.1 迁移 Task Service，并加上只调用该服务的 Task MCP 与 Task Skill
- [x] 4.2 把 Skill/MCP 挂到已配置员工的 AgentScope 会话。工具路径有单元测试；真实会话调用由本地端到端验证完成
- [x] 4.3 将历史执行环境迁为 Worker，保留部署、重启、检测和 Worker 池分配
- [x] 4.4 迁移 API 网关与数字图书馆，并接到 Nexus 导航
- [x] 4.5 接上任务中心、Worker 管理、员工与团队页的关联状态，以及内部唤醒
- [x] 4.6 写明本地启动、环境变量和建议的端到端用例。真实 DeepSeek 调用由本地执行，本环境没有密钥
