## Why

远程数字员工目前需要人工安装依赖、编写 OpenCode 配置和维护 Serve，新机器仅配置 SSH 还不能投入使用。需要把这些环境操作集中到员工配置页，并用现有模型中转与数字图书馆完成接入。

## What Changes

- 为保存了 SSH 地址、账号、密码和工程目录的 Linux 员工提供一键部署与一键重启。
- 安装受验证的 OpenCode、Node.js/npm、Git 等依赖，设置 npm 镜像，合并并备份 SSH 用户的全局 OpenCode 配置。
- 自动配置员工专属中转 Key、模型与数字图书馆 MCP，通过 SSH 访问本机服务，无需开放远程 Serve 公网端口。
- 展示阶段结果、支持取消和重试；工作中的员工禁止部署或重启，旧操作不能覆盖新配置。

## Capabilities

### New Capabilities
- `remote-employee-provisioning`: 远程员工环境部署、配置与 Serve 重启。

### Modified Capabilities
无；平台助手配置与权限契约保持不变。

## Impact

影响员工配置 API/界面、远程环境工具、SSH 隧道及运行前置检查。复用工作环境记录与检查结果，不增加 Task/Session 状态机；不改网关业务模型、不部署 Astra 到远程机器、不编排员工内部执行步骤。
