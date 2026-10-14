# Nexus v1.0.1

Nexus 是数字员工的目录和交流产品。推理、会话、技能、知识和记忆由 **AgentScope 2.0.10 Agent Service** 承担。Nexus 只通过 HTTP 调用它。

本分支上的 `backend/`、`frontend/`、`workspace-ui/` 以及 OpenCode Task / Worker 是原 Astra 树，只作为规范来源，不是 Nexus 的运行入口。

## 页面

- 员工管理：创建、检索、编辑、启用和删除数字员工。没有模型或凭证配置。
- 数字员工：同一员工可以有多条私聊。回复只来自 Agent Service 的事件流。
- 团队交流：讨论成员对等联系。`@员工名` 只唤醒被点名的员工。同事之间继续说话时，由 Agent 调用 `contact_employee`，Nexus 不代写回复。

## 本地启动

API：

```bash
python3 -m venv nexus/api/.venv
nexus/api/.venv/bin/pip install -r nexus/api/requirements-dev.txt
NEXUS_DATA_DIR=nexus/api/data nexus/api/.venv/bin/uvicorn nexus_api.main:app --app-dir nexus/api --port 8120
```

页面：

```bash
cd nexus/web
npm install
npm run dev
```

打开 `http://127.0.0.1:5174`。开发服务器把 `/api` 代理到 `8120`。

未设置 `NEXUS_AGENTSCOPE_BASE_URL` 时，员工目录仍可保存。发送消息会留下用户内容，并说明 AgentScope 未连接、没有生成回复。

接上 Agent Service 时：

```bash
export NEXUS_AGENTSCOPE_BASE_URL=http://127.0.0.1:8000
export NEXUS_AGENTSCOPE_USER_ID=nexus
```

Agent Service 与 Redis 的安装见 [nexus/deploy/agentscope.md](nexus/deploy/agentscope.md)。版本钉在 [nexus/deploy/agentscope.version](nexus/deploy/agentscope.version)。接口记录在 [nexus/docs/agentscope-2.0.10.md](nexus/docs/agentscope-2.0.10.md)。

## 检查

```bash
cd nexus/web && npm run type-check && npm run build
cd ../..
PYTHONPATH=nexus/api nexus/api/.venv/bin/pytest nexus/api/tests
```

OpenSpec 的活跃变更是 `openspec/changes/nexus-v1-0-1/`。工作流仍使用仓库内的 `node .opencode/tools/openspec.mjs`。Superpowers 的实际名单见 `docs/OPENSPEC_SUPERPOWERS.md`。

## Agent Service

Redis、官方 AgentScope 2.0.10 和健康检查见 [nexus/deploy/agentscope.md](nexus/deploy/agentscope.md)。聊天模型由 `nexus/deploy/bootstrap_chat_model.py` 登记到 Agent Service，再通过 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG` 传给新建 Session。页面上没有这一项。

真实联调：

```bash
NEXUS_LIVE_AGENTSCOPE=1 PYTHONPATH=nexus/api \
  nexus/api/.venv/bin/pytest nexus/api/tests/test_live_agentscope.py -s
```

## 已知限制

- 官方 `get_toolkit` 会挂上任务规划、`ToolStop`、定时任务和 Agent Team。Nexus 启动脚本在组装之后卸掉这些名字，保留 `contact_employee` 和工作区文件工具。没有修改 AgentScope 安装包。做法写在 [nexus/deploy/agentscope.md](nexus/deploy/agentscope.md)。
- 本机如果只有 `qwen2.5:3b`，它可能改错同事名字，于是下一跳联系失败。这不是 Nexus 代写的回复。
- 聊天验证目标是 DeepSeek 的 OpenAI 兼容接口：`OPENAI_BASE_URL=https://api.deepseek.com`，`OPENAI_MODEL=deepseek-flash`。密钥用 `OPENAI_API_KEY`，或在它为空时用 `DEEPSEEK_API_KEY`。没有密钥的机器仍用 Ollama。不要把密钥写进仓库。
- 知识库没有启用。AgentScope 2.0.10 不能把 sentence-transformers 或 DeepSeek 当成嵌入模型，本机也没有 `pymilvus`。`GET /knowledge_bases/` 会是 503。本地 `all-MiniLM-L6-v2` 只通过 `nexus/deploy/embedding_smoke.py` 做冒烟。
- `X-User-ID` 仍是 Agent Service 的占位身份。私聊用浏览器里的匿名标识隔离，不是登录账号。
- 图片可以放进 `data` 块。文本模型是否看见图，要换成带视觉的模型后再验证。
