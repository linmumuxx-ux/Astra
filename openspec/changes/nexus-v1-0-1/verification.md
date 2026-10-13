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
