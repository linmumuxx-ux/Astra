# NEXUS 数字图书馆 V1 实现说明

> 历史设计说明：本文的 MCP 数据库关键词搜索、运行身份与引用统计已被 llm_wiki 接入取代。当前接口及已知限制见 [部署文档](../DEPLOYMENT.md#数字图书馆接入-llm_wiki)。
## 1. 现有架构结论

本次实现基于 Astra/NEXUS 现有结构增量完成：

- 前端继续使用 Vue 3、现有 `App.vue` 单层导航、CSS Token 和浅色绿色主题；
- 后端继续使用 FastAPI、SQLAlchemy AsyncSession 与 Alembic；
- Task、Run、DigitalEmployee 仍是知识来源和使用审计的权威对象；
- Web API 与 MCP 共用 `KnowledgeService`，MCP 不直接绕过服务层访问数据表；
- 当前平台没有统一登录，数字图书馆 Web 权限由可信企业网关注入的用户与角色头承接；本地开发保持默认管理员以兼容现有页面。

## 2. V1 组件与文件

### 后端

| 文件 | 职责 |
|---|---|
| `backend/app/models.py` | 知识空间、正文、来源、关系、使用、反馈、收藏、经验依据和审核日志 |
| `backend/alembic/versions/0011_digital_library.py` | SQLite/MySQL 兼容迁移 |
| `backend/app/library_schemas.py` | Web 与 MCP 输入输出契约 |
| `backend/app/library_service.py` | 权限过滤、查询、审核、统计、审计和 MCP 共用业务逻辑 |
| `backend/app/api/library_routes.py` | `/api/library/*` Web API |
| `backend/app/mcp_server.py` | 五个 V1 MCP Tool 与 stdio/Streamable HTTP 入口 |
| `backend/app/bootstrap.py` | 五个基础知识空间初始化 |
| `backend/tests/test_library.py` | Web、权限、候选经验、MCP、审计全链路测试 |

### 前端

| 文件 | 职责 |
|---|---|
| `frontend/src/views/DigitalLibraryView.vue` | 单页状态协调、搜索、筛选、详情和审核 |
| `frontend/src/views/library/LibraryStats.vue` | 五张顶部统计卡片 |
| `frontend/src/views/library/KnowledgeSpacePanel.vue` | 知识空间浏览与维护 |
| `frontend/src/views/library/KnowledgeList.vue` | 服务端筛选、排序、分页列表 |
| `frontend/src/views/library/KnowledgeDetailDialog.vue` | 安全 Markdown、候选依据、审核与关联任务 |
| `frontend/src/views/library/KnowledgeEditorDialog.vue` | 新建和 Markdown 导入 |
| `frontend/src/views/library/KnowledgeUsageSummary.vue` | 最近七天辅助统计 |
| `frontend/e2e/astra.spec.ts` | 导航、搜索、XSS 清理和滚动恢复验收 |

## 3. 数据与状态流

数字员工只能调用 `library_submit_experience` 创建 `type=experience`、`status=candidate` 的记录。服务端验证 Employee、Task、Run 是否存在且关联一致，同时写入 ExperienceEvidence、KnowledgeUsage 和 KnowledgeAudit。

审核者在同一个知识详情弹框中编辑标题、标签、目标空间和 Markdown。发布后状态变为 `published`，记录审核人和时间；当前 V1 使用数据库关键词检索，因此提交事务完成后即可被 `library_search` 命中，不依赖异步索引任务。

`library_search` 记录搜索曝光，但不增加引用次数。只有 `library_get` 把完整知识放入员工上下文时，才记录 `action=reference` 并增加 `reference_count`。

## 4. 搜索策略

V1 对所有已发布且可访问的知识执行服务端统一检索：

1. 权限、空间、状态和类型过滤；
2. 标题、标签、摘要、Markdown 正文和来源字段关键词匹配；
3. MCP 对完整查询与拆分词评分，标题和标签权重最高；
4. 精确错误码、参数名、接口名和中文关键词均可命中；
5. Knowledge Service 接口保持稳定，后续可以在不改变前端/MCP 契约的情况下接入 BM25 或向量召回。

## 5. 权限与安全

Web 网关头：

- `X-Astra-User-Id`：当前用户唯一标识；
- `X-Astra-Role`：`viewer`、`maintainer`、`reviewer` 或 `admin`；
- 生产网关必须清除客户端伪造的同名头后再写入可信值。

能力边界：

| 角色 | 能力 |
|---|---|
| viewer | 浏览已发布知识、收藏、反馈、分享 |
| maintainer | 新建/编辑知识、创建/重命名/停用空间 |
| reviewer | 查看候选经验、发布、驳回、要求补充 |
| admin | 全部能力 |

MCP Streamable HTTP 支持部署环境提供的 Bearer Token；非 loopback 监听但未配置 `ASTRA_MCP_API_KEY` 时拒绝启动。所有 MCP 读写还要求真实 `employee_id`，Task/Run 上下文在服务端校验。

Markdown 在浏览器中先由 `marked` 解析，再由 DOMPurify 过滤；脚本、事件属性和不安全链接不会进入详情 DOM。弹框使用 `max-height: 80vh`、固定 Header/Footer、正文独立滚动，打开时锁定背景页面，关闭后恢复原滚动位置。

## 6. MCP Tools

- `library_search`
- `library_get`
- `library_related`
- `library_submit_experience`
- `library_feedback`

本地 stdio：

```bash
cd backend
../.venv/bin/python -m app.mcp_server
```

OpenCode 员工 Workspace 可通过项目级 `opencode.json` 接入该 stdio Server。`cwd` 与 Python 路径必须替换为实际 Astra 安装目录：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "astra_library": {
      "type": "local",
      "command": ["/opt/astra/.venv/bin/python", "-m", "app.mcp_server"],
      "cwd": "/opt/astra/backend",
      "environment": { "ASTRA_MCP_TRANSPORT": "stdio" },
      "enabled": true,
      "timeout": 10000
    }
  },
  "permission": { "astra_library_*": "allow" }
}
```

保存后运行 `opencode mcp list`，应显示 `astra_library connected`。OpenCode 会将五个工具注册为 `astra_library_library_*`。真实接入验收见 [`DIGITAL-LIBRARY-MCP-OPENCODE-2026-09-01.md`](../verification/DIGITAL-LIBRARY-MCP-OPENCODE-2026-09-01.md)。

共享 Streamable HTTP 通过 `ASTRA_MCP_TRANSPORT=streamable-http` 启用，默认端点为 `http://127.0.0.1:8201/mcp`。Linux 使用 `deploy/systemd/astra-library-mcp.service`，Windows 快速启动器会在该传输模式下自动纳管 MCP 进程。

## 7. 验证结果

- Alembic 从空 SQLite 升级到 `0011_digital_library` 通过；
- Ruff 全量检查通过；
- 后端 70 项测试通过；
- Vue 类型检查与生产构建通过；
- 11 项隔离 Chromium E2E 通过；
- E2E 已验证 Markdown 中的 `<script>` 与 `onerror` 被清除，弹框关闭后背景滚动恢复；
- Task → Knowledge 的后端关联与使用记录已保存，任务详情页的“知识调用”展示留给后续页面增量，不影响 V1 数据闭环；
- OpenCode 1.18.25 已通过真实 stdio MCP 完成五 Tool 调用；Astra Coordinator 的正式 `opencode_server` 任务也完成 search/get/related/feedback 四 Tool 与事件持久化。
