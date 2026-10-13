## 1. 规范与工作流

- [x] 1.1 将 `AGENTS.md` 与 `openspec/config.yaml` 改为 Nexus v1.0.1 边界，并核对 OpenSpec change 可被仓库内 CLI 校验
- [x] 1.2 移走 Astra 活跃 change，按仓库实况记录已存在的 Superpowers，不新增 skill

## 2. AgentScope 2.0.10

- [x] 2.1 写入版本钉与 tag `v2.0.10` 的 Agent、Session、Skill、Knowledge、chat SSE、inbox 和 wakeup 说明
- [x] 2.2 写明 `PER_SESSION` 部署与 `contact_employee` 的投递方式，并给出 Agent Service + Redis 部署说明

## 3. 员工目录与私聊

- [x] 3.1 实现员工创建、检索、更新、启用和删除；技能列表只反映 Agent Service，重复名称被拒绝
- [x] 3.2 实现同一员工的多条私聊、附件和发送；Agent Service 未接受运行时不写入员工回复

## 4. 团队对等交流

- [x] 4.1 实现讨论的创建、编辑和成员调整
- [x] 4.2 实现 `@` 只触发被点名员工，以及联系工具的投递说明；不生成脚本化同事回复

## 5. 页面骨架

- [x] 5.1 用 Vue 3 与 Element Plus 做出员工管理、数字员工、团队交流三页，并完成类型检查与生产构建
- [x] 5.2 在根 README 给出 Nexus 的启动方式，标明旧 Astra 树不是产品入口

## 6. 留待真实 Agent Service 的验证

- [ ] 6.1 对运行中的 AgentScope 2.0.10 与 Redis 做一次创建 Agent、创建两条 Session、SSE 文本增量和 `contact_employee` 唤醒
