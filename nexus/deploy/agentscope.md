# 部署 AgentScope 2.0.10 与 Redis

Nexus 不内嵌 AgentScope。本目录的启动脚本调用已安装的 `agentscope==2.0.10`。

## 版本

见 `agentscope.version`。PyPI 与 GitHub tag `v2.0.10` 都是这个版本，Python `>=3.11`。接口记录在 `../docs/agentscope-2.0.10.md`。

## Redis

```bash
docker compose -f nexus/deploy/docker-compose.yml up -d
```

默认地址是 `localhost:6379`。Agent Service 的 `RedisStorage` 与 `RedisMessageBus` 都连这里。

## Agent Service

另建一个虚拟环境，只安装官方包：

```bash
python3.11 -m venv .venv-agentscope
.venv-agentscope/bin/pip install -r nexus/deploy/agentscope.version
```

`agentscope.version` 的内容是 `agentscope==2.0.10`。然后：

```bash
export NEXUS_API_BASE=http://127.0.0.1:8120
export AGENTSCOPE_REDIS_HOST=localhost
export AGENTSCOPE_REDIS_PORT=6379
export AGENTSCOPE_WORKSPACE_DIR=/data/nexus-workspaces
.venv-agentscope/bin/python nexus/deploy/agent_service.py
```

脚本会：

- 用 `RedisStorage` 与 `RedisMessageBus` 调用 `agentscope.app.create_app`。
- 把 `LocalWorkspaceManager` 的隔离设为 `IsolationPolicy.PER_SESSION`。
- 注册 `contact_employee`，并允许它执行。工具向目标 Session 调用 `deliver_to_inbox`，不生成对方的回复。
- 不注册 Agent Team 工具。

服务监听 `http://127.0.0.1:8000`。Nexus API 用 `NEXUS_AGENTSCOPE_BASE_URL=http://127.0.0.1:8000` 和 `NEXUS_AGENTSCOPE_USER_ID` 访问它。`X-User-ID` 只是 Agent Service 的占位身份，对外发布前要换成真实认证。

模型与凭证在 Agent Service 里配置。Nexus 页面没有这一项。

## 尚未在本环境执行的步骤

本仓库的检查没有启动 Redis 或 Agent Service，因此没有验证真实的创建 Agent、SSE 增量和同事唤醒。对应 OpenSpec 任务是 `6.1`。
