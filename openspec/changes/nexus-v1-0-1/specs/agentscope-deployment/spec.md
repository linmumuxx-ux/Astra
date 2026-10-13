## ADDED Requirements

### Requirement: Nexus uses the pinned Agent Service over HTTP

Nexus SHALL 使用已钉住的 AgentScope 2.0.10 Agent Service 完成 Agent、Session、Skill、Knowledge 与对话推理，并 SHALL 通过 HTTP 调用该服务。Nexus MUST NOT 在自己的进程中实现另一套 Agent、Session 或记忆库，也 MUST NOT 携带 AgentScope 的分叉代码。

#### Scenario: Version pin is recorded

- **WHEN** 开发者查看部署说明
- **THEN** 文档给出 AgentScope 版本 `2.0.10`、对应的 PyPI 发行版和 GitHub tag，并列出该版本真实的 Agent、Session、Skill、Knowledge 与 chat SSE 接口

#### Scenario: Service is not running

- **WHEN** 用户发送聊天消息且 Agent Service 未配置或不可达
- **THEN** 系统保留这条用户消息，并说明没有生成回复
- **THEN** 系统不插入任何助手或同事发言

### Requirement: Deployment does not expose model configuration

Nexus 界面 MUST NOT 提供模型、供应商或凭证的编辑入口。模型配置留在 Agent Service。

#### Scenario: Employee form has no model field

- **WHEN** 用户打开创建或编辑数字员工的表单
- **THEN** 表单不包含模型、供应商或 API 凭证字段

### Requirement: Sessions stay distinct per conversation

部署 MUST 使同一员工的不同对话得到不同的 Session。Agent Service 的 workspace 隔离 MUST 使用按 Session 区分的策略，避免同一用户、同一 Agent 与同一 workspace 被折成一条 Session。

#### Scenario: Two private threads for one employee

- **WHEN** 同一浏览者对同一员工创建两条私聊，且 Agent Service 可用
- **THEN** 两条私聊绑定两个不同的 Session 标识

### Requirement: Session creation carries the deploy-time chat model

当部署提供 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG` 时，Nexus SHALL 在创建 Session 时把该 JSON 作为 `chat_model_config` 传给 Agent Service。该配置引用 Agent Service 中已经登记的 credential。Nexus 界面 MUST NOT 因此增加模型或凭证字段。未提供该变量时，Nexus MUST NOT 自行填写模型。

#### Scenario: Deploy config is present

- **WHEN** 环境变量是一份包含 `type`、`credential_id`、`model` 和 `parameters` 的 JSON，并且用户的消息促使系统创建 Session
- **THEN** 发往 `POST /sessions/` 的正文包含同一份 `chat_model_config`

#### Scenario: Deploy config is absent

- **WHEN** 没有设置 `NEXUS_AGENTSCOPE_CHAT_MODEL_CONFIG`
- **THEN** 创建 Session 的正文不包含 `chat_model_config`
