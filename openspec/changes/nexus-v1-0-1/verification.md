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

# 10. 验收矩阵

日期：2026-10-13。Redis、AgentScope 2.0.10、Nexus API 和 Ollama `qwen2.5:3b` 都在本机。没有第二只更大的本地模型。`ollama list` 只有 `qwen2.5:3b`。

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| Nexus 与 AgentScope 能启动 | 通过 | `GET /health` 版本 `2.0.10`，`storage` 与 `message_bus` 为 `ok`。Nexus `GET /api/v1/runtime` 为 `configured: true`、`reachable: true`。 |
| 创建员工得到真实 Agent | 通过 | 实跑 agent `0d232beafb2f4e069623cd797d321bbc`。删除后 `deleted: true`。 |
| 修改职责会进入之后的运行 | 通过 | 修改后的 Agent `system_prompt` 含「改过的职责说明」和「改过的工作指令」。聊天时读取的是当前 Agent 记录里的这段提示。 |
| 禁用和删除是真的 | 通过 | 禁用私聊 HTTP 409；重新启用后接受运行；删除后 Agent 不在列表里。 |
| 私聊多轮流式、切换历史 | 通过 | 两条 Session `d37367bc9eec4391a1d0b19ba0918ee2` 与 `ed70fce00d4f45e6a4bab77190299009`。两轮文本增量都是模型自己的「在」。 |
| 刷新或重启后恢复，匿名隔离 | 通过 | 重启 Nexus API 后，原匿名标识仍读到「重启口令 a3d265」，Session `9d7bbdfebefb49479140632c38513fe3` 还在。另一个标识得到 404。 |
| 附件进入模型输入 | 通过 | 团队实跑里 `FAIL-TOKEN-55` 出现在运营 Session。私聊实跑里 `LOG-TOKEN-88` 出现在 Session。单元测试记录了图片 `data`/`base64` 块。这个文本模型是否看见图，没有单独证明。 |
| 三位员工，A 联系 B，身份正确，不无限循环 | 部分通过 | 见下面的团队实跑。A 到 B 的联系和回复是真实的。B 没有用正确名字联系到 C。重复联系返回 409。 |
| 没有伪造的 AI 回复 | 通过 | 页面和 API 只展示 Session 里的助手文本。Agent Service 未接受运行时不写入员工回复。 |

团队实跑命令：

```bash
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest \
  nexus/api/tests/test_live_agentscope.py::test_team_discussion_shows_peer_identities_and_stops_repeat_contact \
  nexus/api/tests/test_live_agentscope.py::test_employee_management_against_live_agentscope \
  nexus/api/tests/test_live_agentscope.py::test_private_chat_streams_and_isolates_anonymous_owners -s
```

`3 passed in 92.51s`。团队打印：

```json
{"ops_tools": ["contact_employee", "contact_employee"], "ops_fragments": "{\"message\": \"请看自动化失败。\", \"employee_name\": \"自动f6766d\"}已把消息交给对方。对方将自行推理，这里没有代替对方写出答复。", "ops_deltas": "等待自动f6766d的回复。", "eng_tools": ["contact_employee", "contact_employee"], "eng_fragments": "{\"employee_name\": \"同自动化f6766d\", \"message\": \"请看自动化失败。\"}没有找到可联系的员工", "eng_deltas": "在当前的对话中，没有找到可以联系到的员工。请确认是否有其他同事可以协助检查自动化失败的问题。", "tool_deltas": "", "sessions": ["emp_f1fd841f6959", "emp_fca309b5b68f"], "senders": ["emp_f1fd841f6959", "emp_fca309b5b68f", "user"], "log_seen": true, "resolve_statuses": [200, 409], "stream_errors": []}
```

运营调用的是 `contact_employee`，名字是自动化工程师的真名。工具结果是投递说明，不是代写的同事结论。运营自己的文本是「等待自动f6766d的回复。」自动化工程师的文本在频道里用另一个员工 id 显示。它接着调用 `contact_employee` 时把名字写成了「同自动化f6766d」，解析返回没有找到这个员工，所以工具工程师没有被唤醒。同一句话再次解析是 409。

卸工具之前的一轮里，模型先调用了八次 `ToolStop`，然后用「同僚」调用 `contact_employee`。那一轮没有形成同事回复。`ToolStop`、`Schedule*`、任务规划和 Agent Team 现在都在官方组装之后卸掉。

## 知识库阻塞

没有启用。`pymilvus` 未安装。本机唯一模型是聊天模型 `qwen2.5:3b`，没有嵌入模型。Agent Service 健康检查里的 `knowledge_base` 是 `disabled`。`GET /api/v1/knowledge` 为 `available: false`。手写知识库标识仍会被拒绝。

后续确认见第 11 节：DeepSeek 没有嵌入模型，AgentScope 2.0.10 也不能把 `all-MiniLM-L6-v2` 注册成知识库嵌入。知识库继续关闭。本地冒烟不改变这个状态。

## 11. DeepSeek Flash 接线与本地嵌入

日期：2026-10-14。环境里没有 `OPENAI_API_KEY`，也没有 `DEEPSEEK_API_KEY`。没有调用 `https://api.deepseek.com`，没有把密钥写进仓库。

聊天引导仍走 `openai_credential`。验证机应设置：

```bash
NEXUS_CHAT_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
OPENAI_API_KEY=${DEEPSEEK_API_KEY}
```

`OPENAI_API_KEY` 为空时脚本读取 `DEEPSEEK_API_KEY`。没有这两个变量时，openai 模式直接退出，不会登记空凭证。实测：

```text
openai 需要 OPENAI_MODEL，以及 OPENAI_API_KEY 或 DEEPSEEK_API_KEY
```

本机实跑仍用 Ollama。Redis `PONG`。`GET /health` 为 AgentScope `2.0.10`，`knowledge_base` 为 `disabled`。`NEXUS_CHAT_PROVIDER=ollama` 的引导复用已有凭证，打印：

```json
{"type": "ollama_credential", "credential_id": "3dac2b14d6604d319e73b41190b57ff7", "model": "qwen2.5:3b", "parameters": {}}
```

打印里没有密钥。单元测试 `pytest nexus/api/tests/test_bootstrap_chat_model.py nexus/api/tests/test_api.py`：`27 passed`。

嵌入冒烟单独使用 `nexus/deploy/.venv-embedding`，没有装进 Agent Service，也没有安装 `pymilvus`。`embedding_smoke.py` 的输出：

```json
{"model": "all-MiniLM-L6-v2", "dims": 384, "similar": 0.6079, "dissimilar": 0.0187}
```

维度 384。两句相近英文的余弦高于不相近的那句。这个结果没有写入知识库。

## 12. 邮箱续跳、权限询问和回复可见

日期：2026-10-14。没有 `DEEPSEEK_API_KEY`，这一节的实跑仍是 Ollama `qwen2.5:3b`。

邮箱会话可以再联系下一位同事，次数算在发起那场私聊的 `private:{conversation_id}` 里，不按员工累计。同事写在自己邮箱里的正文，读私聊时带回来，发送方不代写。邮箱和团队 Session 设为 `dont_ask`。未设置 `NEXUS_DATA_DIR` 时目录在 API 包旁边；相对路径按仓库根目录解析。SSE 先从上一轮已落盘的 `event_cursor` 之后开始，本轮 `REPLY_END` 之后写 `NEXUS_RUN_FINISHED` 并结束连接。

`pytest nexus/api/tests/test_api.py nexus/api/tests/test_bootstrap_chat_model.py`：`31 passed`。

Ollama 实跑 `test_task_6_1_agent_sessions_sse_and_peer_wakeup`：`1 passed in 86.01s`。

```json
{"agent_id": "d9207d4002154f6692f83b222cb6633c", "sessions": ["e38ce5062042401ebe72388a1f5e4fe1", "875bbb7245ac402ea010e6bde3b2def5"], "private_deltas": "收到。", "caller_tools": ["contact_employee", "contact_employee"], "peer_deltas": "42"}
```

同事邮箱里的回复是「42」，没有停在权限询问。没有对 `deepseek-flash` 发起聊天。

2026-10-15 的 deepseek-flash 复跑里，三人续跳、`NEXUS_RUN_FINISHED`、权限询问和团队讨论都通过。私聊里看不到同事回复：`json.dumps` 把换行转成 `\\n`，而且 hint 和答复在同一条 assistant 消息里，匹配后又跳过了这条消息。现在按原文比较 hint 和正文，并读入这条答复；下一次唤醒的 assistant 不再算进来。频道里 AgentScope 的无时区本地时间会先收成 UTC，再和用户消息一起按时刻排序。单元测试 `33 passed`。
