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

## 下一阶段入口

OpenSpec 任务 `6.1`：对运行中的 AgentScope 2.0.10 和 Redis 验证创建 Agent、同一员工的两条 Session、SSE 文本增量，以及 `contact_employee` 的 inbox / wakeup。在此之前不要把骨架里的失败说明换成模拟回复。
