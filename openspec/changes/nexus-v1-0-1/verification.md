# 6.1 验证记录

日期：2026-10-13。

环境：

- Redis：本机 `redis-server` 7，`redis-cli ping` 为 `PONG`。这台机器没有 Docker，所以没有用 compose。
- Agent Service：`nexus/deploy/.venv-agentscope` 里的官方 `agentscope==2.0.10`，`GET /health` 的 `version` 为 `2.0.10`，`storage` 与 `message_bus` 为 `ok`。
- 模型：Ollama `qwen2.5:3b`，经 `bootstrap_chat_model.py` 登记为 `ollama_credential`，再写入 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG`。Nexus 页面没有模型字段。

命令：

```bash
bash nexus/deploy/redis.sh
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/agent_service.py
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/bootstrap_chat_model.py
# 将打印的 JSON 设为 NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG 后启动 Nexus API
bash nexus/deploy/healthcheck.sh
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py -s
```

结果：`1 passed in 31.48s`。测试打印：

```json
{"agent_id": "a96da55d15f34da19cad4f3e87ba36da", "sessions": ["82ee037db2484d218e8d48fe4a461fe0", "bcb079542345444a8759b002fe4f6838"], "private_deltas": "{\"name\": \"TaskGet\", \"arguments\": {\"task_id\": \"1\"}}", "caller_tools": ["contact_employee", "contact_employee", "contact_employee", "contact_employee"], "peer_deltas": "XML_tag_here"}
```

同一员工的两条 Session 不同。私聊的 SSE 有文本增量。`contact_employee` 出现在调用方事件里，对方邮箱流有模型自己的增量。Nexus 的消息表只有 `user`。`qwen2.5:3b` 没有按提示只回复指定数字。

# 7.1 员工管理验证记录

日期：2026-10-13。沿用上面的 Redis、AgentScope 2.0.10 和 Ollama credential。Nexus API 使用更新后的目录校验。

命令与直接探测：

```bash
curl -sS -H 'X-User-ID: nexus' http://127.0.0.1:8000/knowledge_bases/
# HTTP 503
# {"detail":"Knowledge base feature is disabled — pass a knowledge_base_manager to create_app() to enable it."}

curl -sS http://127.0.0.1:8120/api/v1/knowledge
# {"available":false,"items":[]}

curl -sS http://127.0.0.1:8120/api/v1/tools
# Bash, Edit, Glob, Grep, Read, Write, contact_employee

curl -sS http://127.0.0.1:8120/api/v1/skills
# {"available":true,"items":[]}

NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest \
  nexus/api/tests/test_live_agentscope.py::test_employee_management_against_live_agentscope -s
```

结果：`1 passed in 0.36s`。测试打印：

```json
{"agent_id": "48a90bf0b957493090e03d5472101217", "knowledge_available": false, "tools": ["Bash", "Edit", "Glob", "Grep", "Read", "Write", "contact_employee"], "disabled_status": 409, "enabled_accepted": true, "deleted": true}
```

创建和修改后的职责说明、工作指令写进了 Agent 的 `system_prompt`。同名员工被拒绝。禁用后的私聊是 409，没有开始新运行；重新启用后 Agent Service 接受了 `POST /chat`。删除后 `GET /agent/` 里没有这个 Agent。联系已禁用员工时解析接口返回 404，不交出 Session。

未在这次记录里做的事：没有给 `create_app` 传入 `knowledge_base_manager`，所以没有真实知识库可供选中。技能库当时为空，也没有 SkillHub，不能把技能装进 workspace。官方 `get_toolkit` 仍会自行挂上任务和团队工具，员工档案里的工具选择不会把它们卸掉。

# 8. 私聊验证记录

日期：2026-10-13。仍是本机 Redis、AgentScope 2.0.10 和 Ollama `qwen2.5:3b`。没有安装 `pymilvus`，也没有嵌入模型，所以没有打开知识库目录，也没有写入示例技能。

命令：

```bash
PYTHONPATH=nexus/api nexus/api/.venv/bin/pytest nexus/api/tests/test_api.py -q
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest \
  nexus/api/tests/test_live_agentscope.py::test_private_chat_streams_and_isolates_anonymous_owners -s
```

单元测试 19 passed。实跑 `1 passed in 25.17s`。打印：

```json
{"agent_id": "338684e50b6f4ebfa71250f71f81c90c", "sessions": ["dbec10b3f9094248b6cc9aee84bcfa7e", "1aa0f329d80c40e1b119fb4df60fff44"], "text_deltas": "{}\n{}\n{}\n{}\nNone of the available employees can be contacted for this request. P", "second_deltas": "你似乎在重复同一个指令或问题。请提供更多的信息，以便我能更好地帮助你。", "log_in_session": true, "other_owner": 404, "disabled_status": 409}
```

同一条对话的两轮共用第一条 Session，另一条对话是第二条 Session。日志正文进入了 AgentScope 保存的用户消息。另一个匿名标识不能读取。禁用后是 409。`qwen2.5:3b` 没有按提示只回复「在」。图片以 `data` 块发送；这个文本模型是否看见图，这次没有单独证明。

浏览器在 `http://127.0.0.1:5174/chat` 粘贴并移除了 `shot.png`，拖入并看到了 `drop.log`，记忆页为只读，没有员工编辑表单，发送后的用户消息留在页面上。

# 9. 团队讨论验证记录

日期：2026-10-13。仍是本机 Redis、AgentScope 2.0.10 和 Ollama `qwen2.5:3b`。没有打开知识库，也没有写入示例技能。

单元测试：

```bash
PYTHONPATH=nexus/api nexus/api/.venv/bin/pytest nexus/api/tests/test_api.py -q
```

`21 passed`。其中：只点名的员工会收到 `POST /chat`；日志正文进入该员工的内容块；尚未被点名的同事在 `contact_employee` 解析时得到这条讨论自己的 Session，而不是邮箱；同一句话再次解析返回 409；同一发送方第三次联系被拒绝；另一位同事仍可以再联系下一位；禁用同事返回 404。读回的助手句标的是自动化工程师的员工 id，消息表里仍然只有 `user`。

实跑：

```bash
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest \
  nexus/api/tests/test_live_agentscope.py::test_team_discussion_shows_peer_identities_and_stops_repeat_contact -s
```

`1 passed in 34.51s`。打印：

```json
{"ops_tools": ["TaskGet", "TaskGet"], "ops_deltas": "{}\n{\"name\": \"contact_employee\", \"arguments\": {\"employee_name\": \"unknown_employee\", \"message\": \"Task not found. Please provide the correct task ID and retry.\"}}", "eng_tools": [], "eng_deltas": "", "tool_deltas": "", "sessions": ["emp_7b7ae8d653df"], "senders": ["emp_7b7ae8d653df", "user"], "log_seen": true, "resolve_statuses": [200, 409], "stream_errors": []}
```

人类消息只触发了运营。日志 `FAIL-TOKEN-55` 进入了该员工的 Session。频道里的助手文本属于运营自己的员工 id。解析为自动化工程师创建了讨论 Session，重复同一句话返回 409。同一轮更早的两次实跑里，模型分别调用了 `TaskGet` 和连续多次 `TeamCreate`，都没有真正调用 `contact_employee`。`contact_employee` 出现在文本增量里，不是工具事件。因此运营 → 自动化 → 工具这一跳没有由模型自己走完。

为了单独确认投递路径，又用 `contact_employee` 内部的 `deliver_to_inbox` 向已经解析出的讨论 Session 写了一条提示。这不是模型自己选的工具。对方 Session `9c0578ce0a5c49008367b297a37bd902` 与邮箱 `ffcc672dcba9494d8be1cfa2a3142c1f` 不同。频道记录里的发言人是：

- `user`：人类的点名消息
- `emp_a365d98d488a`：被点名员工自己的文本，内容是 `TaskGet`
- `emp_3e0f6364c810`：被叫醒同事自己的文本，开头是 “None of the provided functions or methods are needed”

两位员工的文本没有互换。同事的话来自模型，不是 Nexus 写好的回复。

浏览器打开 `http://127.0.0.1:5174/team`：创建了「浏览器讨论」，6 名员工出现在勾选列表里；编辑后成员数为 4。输入框写明可以拖入或粘贴图片。拖入 `shot.png` 后能预览，移除后预览消失。未点名就发送时，页面说明没有触发任何人。页面没有员工编辑表单。
