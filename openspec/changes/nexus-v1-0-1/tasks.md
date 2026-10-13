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

- [x] 8.1 同一匿名标识可与一位员工进行多条私聊；刷新后恢复 Session 与用户消息；另一个匿名标识读不到这些对话
  - 2026-10-13：`pytest nexus/api/tests/test_api.py` 19 passed。其中两个匿名标识互不可见，API 用同一数据目录重新创建后仍能取回用户消息。
  - 实跑 `test_private_chat_streams_and_isolates_anonymous_owners`：`1 passed in 25.17s`。两条 Session `dbec10b3f9094248b6cc9aee84bcfa7e` 与 `1aa0f329d80c40e1b119fb4df60fff44`。另一匿名标识读取对话得到 404。
- [x] 8.2 文本和图片附件按 AgentScope 消息块发送；事件流文本来自 Session，不由 Nexus 代写；禁用员工不能开始新运行
  - 同一条实跑里，两轮都收到 `TEXT_BLOCK_DELTA`。第一轮增量是模型自己的文本，不是「在」。第二轮增量是「你似乎在重复同一个指令或问题。请提供更多的信息，以便我能更好地帮助你。」
  - 日志 `LOG-TOKEN-88` 出现在该 Session 的 `GET /sessions/{id}/messages` 里。附件下载内容与上传一致。禁用后私聊为 409。
  - MockTransport 记录了日志正文进入文本块、图片进入 `data`/`base64` 块，Session 里的助手句「模型自己的回复」被读回，Nexus 没有写「已解析」。
  - 浏览器打开 `/chat`：粘贴 `shot.png` 后能预览并移除；拖入 `drop.log` 后能预览；记忆页写明只读且没有员工编辑表单；发送后用户消息留在对话里。

## 9. 团队对等交流

- [x] 9.1 讨论可增删成员。`@` 只触发被点名员工。`contact_employee` 会为同一讨论里尚未被点名的同事创建 Session 并投递，不代写回复
  - 2026-10-13：`pytest nexus/api/tests/test_api.py` 21 passed。解析会创建讨论 Session，不额外调用 `/chat`。
  - 浏览器创建「浏览器讨论」后再编辑，成员数变为 4。未点名发送时没有触发员工。
  - 实跑里 `qwen2.5:3b` 没有自己调用 `contact_employee`，而是调用了 `TaskGet` 或 `TeamCreate`。用工具内部的 `deliver_to_inbox` 向讨论 Session 投递后，同事被唤醒，回复标的是同事自己的员工 id。
- [x] 9.2 同一频道按员工身份显示各自 Session 的发言，附件进入模型输入。同一句话和超过次数的联系会被拒绝，下一位同事仍能继续联系一位成员
  - 同一轮实跑 `1 passed in 34.51s`。`FAIL-TOKEN-55` 进入运营的 Session。频道发送者只有 `user` 和运营的员工 id。重复联系返回 409。
  - 直接投递后的频道记录同时出现两位员工的 id，文本没有对调。模型没有继续联系第三位。

## 10. 验收与对等工具收口

- [x] 10.1 按产品验收项记录通过和未通过，并给出当次证据
  - 2026-10-13：部署健康检查、员工、私聊、团队实跑和 API 重启恢复见 `verification.md` 第 10 节。
- [x] 10.2 卸下会抢走 `contact_employee` 的任务规划和 Agent Team 工具，并用实跑证明工具事件里出现 `contact_employee`
  - 官方 `get_toolkit` 仍会组装这些工具。启动脚本在组装后调用 `Toolkit.remove_tool`，并丢掉空的非 basic 工具组。没有修改 AgentScope 安装包。
  - 卸掉 `ToolStop` 之前，模型先连续调用 `ToolStop`，再用错误名字调用 `contact_employee`。卸掉之后的实跑里，运营调用了 `contact_employee`，工具结果是「已把消息交给对方」，自动化工程师在同一频道里用自己的员工 id 作了回复。事件里没有 `TeamCreate`、`TaskGet` 或 `ToolStop`。
- [x] 10.3 知识库只有在依赖和嵌入模型都真实可用时才启用；否则写明阻塞
  - 本机没有 `pymilvus`。`ollama list` 只有 `qwen2.5:3b`，没有嵌入模型。`GET /health` 的 `knowledge_base` 仍是 `disabled`。没有启用 `knowledge_base_manager`。
