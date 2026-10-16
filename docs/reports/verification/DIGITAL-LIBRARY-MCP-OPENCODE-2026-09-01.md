# 数字图书馆 MCP × OpenCode 真实接入验收

日期：2026-09-01  
环境：macOS，本地 SQLite，OpenCode 1.18.25，`deepseek/deepseek-v4-flash`

## 结论

数字图书馆 MCP 已作为项目级本地 stdio Server 接入 OpenCode。OpenCode 能自动启动 `app.mcp_server`、发现五个 Tool，并由真实模型完成结构化调用。Astra Coordinator 创建的正式任务也能在 OpenCode Server Session 中调用相同 MCP，保存 Tool 事件、Run 和任务结果。

## OpenCode 配置

当前员工 Workspace：`services/task-platform/workspaces`  
项目级配置：`services/task-platform/workspaces/opencode.json`

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "astra_library": {
      "type": "local",
      "command": ["/Users/niuniu/程序/Astra/.venv/bin/python", "-m", "app.mcp_server"],
      "cwd": "/Users/niuniu/程序/Astra/backend",
      "environment": { "ASTRA_MCP_TRANSPORT": "stdio" },
      "enabled": true,
      "timeout": 10000
    }
  },
  "permission": { "astra_library_*": "allow" }
}
```

`opencode mcp list` 与 OpenCode Server `/mcp` 均返回 `astra_library: connected`。另启动隔离的 OpenCode Server 后，未做动态注入即从 Workspace 配置自动恢复连接，证明配置可跨 Server 重启生效。

## 五 Tool 真实调用

OpenCode Session：`ses_fa4a2fd47ffefFJWgDb1CSWDBc`

| Tool | OpenCode 实际工具名 | 结果 |
|---|---|---|
| `library_search` | `astra_library_library_search` | 命中 `ERR_MCP_9001` 两条知识，Top1 score 43.0 |
| `library_get` | `astra_library_library_get` | 返回完整 Markdown，引用次数增加 1 |
| `library_related` | `astra_library_library_related` | 返回显式关联的回归清单 |
| `library_feedback` | `astra_library_library_feedback` | 创建 helpful 反馈，数量增加 1 |
| `library_submit_experience` | `astra_library_library_submit_experience` | 创建 `type=experience`、`status=candidate` 的候选经验及 PASS 证据 |

模型最终返回 `MCP_REAL_E2E_COMPLETE`。数据库同步保存五条 `KnowledgeUsage`，`tool_name` 分别为 `library_search`、`library_get`、`library_related`、`library_feedback`、`library_submit_experience`。

## Astra 正式任务链

- Task：`T-20260901-A028E2`
- Run：`RUN-EC9D2C635A`
- OpenCode Session：`ses_fa4a1d31bffe1TwdtNqIpKOBpi`
- Executor：`opencode_server`
- Model：`deepseek/deepseek-v4-flash`
- 结果：`COMPLETED`，3 项验收标准全部 `SATISFIED`

Astra 持久化了 search/get/related/feedback 四个 MCP Tool 的 `pending → running → completed` 事件，Run 的 `tool_call_count=4`。任务结果保存了搜索命中、读取知识 ID、关联知识 ID和反馈结果。

验收完成后，三条临时知识、候选经验、KnowledgeUsage/Feedback/Audit/Evidence、Astra 测试 Task/Run/TaskSession 及本地记录文件均已清理；OpenCode 项目级 MCP 配置、验收 Session 与当前 `connected` 连接保留。

## 边界

本次完成的是 OpenCode 本地 stdio MCP 真实接入。Streamable HTTP、Bearer Token、公司 MySQL、企业网关以及远程 Linux/Windows Workspace 的正式环境接入仍需单独现场验收。
