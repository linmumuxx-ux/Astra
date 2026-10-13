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

## 6. 真实 Agent Service

- [x] 6.1 对运行中的 AgentScope 2.0.10 与 Redis 做一次创建 Agent、创建两条 Session、SSE 文本增量和 `contact_employee` 唤醒
  - 验证命令：`NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py -s`
  - 2026-10-13 在本机 `redis-server`（没有 Docker）和 Ollama `qwen2.5:3b` 上通过。健康检查里的 Agent Service 版本是 `2.0.10`。
  - 当次输出：agent `a96da55d15f34da19cad4f3e87ba36da`；两条 Session `82ee037db2484d218e8d48fe4a461fe0` 与 `bcb079542345444a8759b002fe4f6838`。
  - 私聊 SSE 收到 `TEXT_BLOCK_DELTA`。调用方事件里出现四次 `contact_employee`。对方邮箱流的文本增量是模型自己写出的 `XML_tag_here`，Nexus 保存的消息仍然只有 `user`。
  - `qwen2.5:3b` 没有稳定按提示只回复指定数字。这是模型输出，不是 Nexus 代写的同事回复。

## 7. 员工管理

- [x] 7.1 员工的创建、检索、修改、启用、禁用和删除调用正在运行的 AgentScope；知识和工具只接受目录中的标识；禁用后不能开始新的运行
  - 验证命令：`NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py::test_employee_management_against_live_agentscope -s`
  - 2026-10-13 通过，`1 passed in 0.36s`。Agent Service `GET /health` 版本 `2.0.10`，`knowledge_base` 为 `disabled`。
  - `GET /knowledge_bases/` 返回 503：`Knowledge base feature is disabled — pass a knowledge_base_manager to create_app() to enable it.` Nexus `GET /api/v1/knowledge` 为 `{"available": false, "items": []}`。手写知识库标识被拒绝。
  - `GET /api/v1/skills` 可读，当时技能库是空列表。虚构技能 `not-a-real-skill` 被拒绝。
  - `GET /api/v1/tools` 为 Bash、Edit、Glob、Grep、Read、Write、`contact_employee`。`query_task` 被拒绝。
  - 当次输出：agent `48a90bf0b957493090e03d5472101217`；禁用私聊 HTTP 409；重新启用后 `POST /chat` 被接受；删除后该 Agent 不在 `GET /agent/`。
  - 同一轮 `pytest nexus/api/tests/test_api.py` 为 16 passed。MockTransport 记录了：目录外的知识与工具返回 422；禁用期间没有 `POST /chat`；禁用员工的 `contact_employee` 解析返回 404，正文含「禁用」。

## 8. 数字员工私聊

- [ ] 8.1 同一匿名标识可与一位员工进行多条私聊；刷新后恢复 Session 与用户消息；另一个匿名标识读不到这些对话
- [ ] 8.2 文本和图片附件按 AgentScope 消息块发送；事件流文本来自 Session，不由 Nexus 代写；禁用员工不能开始新运行
