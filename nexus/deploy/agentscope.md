# 部署 AgentScope 2.0.10 与 Redis

Nexus 不内嵌 AgentScope。本目录的启动脚本调用已安装的 `agentscope==2.0.10`。

## 版本

见 `agentscope.version`。PyPI 与 GitHub tag `v2.0.10` 都是这个版本，Python `>=3.11`。接口记录在 `../docs/agentscope-2.0.10.md`。

## Redis

有 Docker 时：

```bash
docker compose -f nexus/deploy/docker-compose.yml up -d
```

没有 Docker 时，`nexus/deploy/redis.sh` 会在本机 `redis-server` 上监听 `127.0.0.1:6379`。两者都没有时，脚本退出并说明原因。

Agent Service 的 `RedisStorage` 与 `RedisMessageBus` 都连这里。

## Agent Service

另建一个虚拟环境，只安装官方包和它声明的 extras（`service`、`storage-redis`、`model-ollama`）：

```bash
python3 -m venv nexus/deploy/.venv-agentscope
nexus/deploy/.venv-agentscope/bin/pip install -r nexus/deploy/requirements.txt
```

`agentscope.version` 的内容仍是 `agentscope==2.0.10`。`requirements.txt` 使用同一版本，并带上官方 extras。然后：

```bash
set -a
source nexus/deploy/env.example
set +a
export NEXUS_API_BASE=http://127.0.0.1:8120
bash nexus/deploy/redis.sh
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/agent_service.py
```

脚本会：

- 用 `RedisStorage` 与 `RedisMessageBus` 调用 `agentscope.app.create_app`。
- 把 `LocalWorkspaceManager` 的隔离设为 `IsolationPolicy.PER_SESSION`。
- 注册 `contact_employee`，并允许它执行。工具把对方姓名和原文交给 Nexus 解析，再向目标 Session 调用 `deliver_to_inbox`，不生成对方的回复。解析返回 4xx 时，工具把说明交回模型并停止投递。
- 不注册 Agent Team。官方 `get_toolkit` 仍会把任务规划、`ToolStop`、定时任务和 Agent Team 放进工具组。`agent_service.py` 在 `create_app` 之前替换聊天和实时服务使用的 `get_toolkit`：先调用官方组装，再 `Toolkit.remove_tool` 卸掉 `TaskCreate`、`TaskGet`、`TaskList`、`TaskUpdate`、`ToolStop`、`TeamCreate`、`AgentCreate`、`TeamSay`、`TeamDelete`、`AgentInvite`、`ScheduleCreate`、`ScheduleDelete`、`ScheduleList`、`ScheduleView`。空的非 basic 工具组也会去掉，避免模型再去激活它们。`contact_employee` 和工作区的 Bash、Read、Write 等仍然保留。没有改 AgentScope 安装包。
- 不传入 `knowledge_base_manager`。AgentScope 2.0.10 的嵌入模型只来自 OpenAI、Ollama、Gemini、DashScope 凭证，没有 sentence-transformers 适配。DeepSeek 凭证只有聊天模型，不能把 `deepseek-flash` 当成嵌入。本机 Ollama 只有聊天模型 `qwen2.5:3b`。向量库要官方 extra `vdb-milvus`（`pymilvus` / Milvus Lite），当前 Agent Service 环境没有安装。知识库目录保持关闭。`GET /knowledge_bases/` 因此不可用，员工页面不能手写新的知识库标识。本地嵌入只做冒烟：另建虚拟环境安装 `requirements-embedding.txt`，运行 `embedding_smoke.py`。技能库为空时也不写入示例技能。

服务默认监听 `http://127.0.0.1:8000`。健康检查：

```bash
bash nexus/deploy/healthcheck.sh
```

它要求 Redis 返回 `PONG`，并且 `GET /health` 带 `X-User-ID` 成功。`X-User-ID` 只是 Agent Service 的占位身份，对外发布前要换成真实认证。

## 聊天模型

Nexus 页面没有模型或密钥字段。模型登记在 Agent Service：

没有付费密钥时用本机 Ollama。有 DeepSeek 密钥的验证机使用 OpenAI 兼容凭证，模型 id 是 `deepseek-flash`：

```bash
export NEXUS_CHAT_PROVIDER=openai
export OPENAI_BASE_URL=https://api.deepseek.com
export OPENAI_MODEL=deepseek-flash
export OPENAI_API_KEY="${DEEPSEEK_API_KEY}"
# 也可以不设 OPENAI_API_KEY，只导出 DEEPSEEK_API_KEY。脚本在前者为空时读取后者。
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/bootstrap_chat_model.py
```

`OPENAI_BASE_URL` 写入 `openai_credential.base_url`。AgentScope 的 `OpenAIChatModel` 会把这个地址传给客户端。打印的 JSON 只有 `type`、`credential_id`、`model` 和空的 `parameters`，不含密钥。同一类型里，只有 `base_url`（Ollama 则是 `host`）一致的凭证才会复用。

本机默认仍是 `NEXUS_CHAT_PROVIDER=ollama`。没有密钥时不要改成 openai，脚本会直接退出，不会登记空凭证。

把打印出的 JSON 设为 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG`，再启动 Nexus API。创建 Session 时会带上这份 `chat_model_config`。变量为空时，Session 没有模型，发送消息不会被改成模拟回复。

## 本地嵌入冒烟

知识库保持关闭。要确认 `all-MiniLM-L6-v2` 能在本机编码：

```bash
python3 -m venv nexus/deploy/.venv-embedding
nexus/deploy/.venv-embedding/bin/pip install -r nexus/deploy/requirements-embedding.txt
nexus/deploy/.venv-embedding/bin/python nexus/deploy/embedding_smoke.py
```

脚本打印维度，以及两句相近英文和一句不相近英文的余弦。`all-MiniLM-L6-v2` 是英文模型。相近的一对必须更高。这个结果不写入 Agent Service。

## 任务 6.1

服务都起来之后：

```bash
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py -s
```

未设置 `NEXUS_LIVE_AGENTSCOPE=1` 时，这条测试会跳过，避免在没有 Agent Service 的环境里失败。
