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
- 注册 `contact_employee`，并允许它执行。工具向目标 Session 调用 `deliver_to_inbox`，不生成对方的回复。
- 不注册 Agent Team 工具。

服务默认监听 `http://127.0.0.1:8000`。健康检查：

```bash
bash nexus/deploy/healthcheck.sh
```

它要求 Redis 返回 `PONG`，并且 `GET /health` 带 `X-User-ID` 成功。`X-User-ID` 只是 Agent Service 的占位身份，对外发布前要换成真实认证。

## 聊天模型

Nexus 页面没有模型或密钥字段。模型登记在 Agent Service：

```bash
# 本机 Ollama 已提供 NEXUS_OLLAMA_MODEL，或改为 NEXUS_CHAT_PROVIDER=openai
nexus/deploy/.venv-agentscope/bin/python nexus/deploy/bootstrap_chat_model.py
```

把打印出的 JSON 设为 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG`，再启动 Nexus API。创建 Session 时会带上这份 `chat_model_config`。变量为空时，Session 没有模型，发送消息不会被改成模拟回复。

## 任务 6.1

服务都起来之后：

```bash
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py -s
```

未设置 `NEXUS_LIVE_AGENTSCOPE=1` 时，这条测试会跳过，避免在没有 Agent Service 的环境里失败。
