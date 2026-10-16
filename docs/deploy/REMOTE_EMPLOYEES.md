# Linux 远程员工部署

在「数字员工」中新建或编辑员工，选择 Linux 远程，填写 IP、SSH 端口、用户名、密码和绝对工程目录后保存。检测失败时配置仍保存，可以直接点击「一键部署」。首次安装需要下载软件或编译 Git，请保持页面连接；完成后的环境状态为「可用」。已有环境可点击「重启 OpenCode Serve」。

## 平台准备

平台的 API 中转必须启用并至少有一个启用的模型路由。员工模型留空时部署选择首个路由，也可填写 `astra-gateway/<路由模型>`。部署为员工创建专属 Key，重复部署复用有效 Key；失败时吊销本次新建 Key，修复后可再次部署。

数字图书馆须运行 HTTP MCP。平台 `.env` 设置 `ASTRA_MCP_TRANSPORT=streamable-http`、`ASTRA_MCP_API_KEY=<服务密钥>`，重启平台并运行 `python -m app.mcp_server`（在 backend 内，使用项目虚拟环境）。平台和图书馆服务须加载同一份配置。服务管理命令见 [部署文档](DEPLOYMENT.md)。

默认通过 SSH 反向隧道连接 Astra 所在主机的 API 中转和图书馆，远端不需要公开 Serve 端口。SSH 服务须允许 TCP 转发。生产中可设置 `ASTRA_REMOTE_GATEWAY_PUBLIC_URL` 和 `ASTRA_MCP_PUBLIC_URL`，使用远端可达的 HTTPS 地址。

| 配置项 | 默认值 | 用途 |
| --- | --- | --- |
| `ASTRA_REMOTE_OPENCODE_VERSION` | `1.18.33` | 固定 OpenCode npm 包版本 |
| `ASTRA_REMOTE_NODE_VERSION` | `22.23.3` | 固定 Node.js 版本 |
| `ASTRA_REMOTE_NPM_REGISTRY` | `https://registry.npmmirror.com` | 当前 SSH 用户的 npm registry |
| `ASTRA_REMOTE_DEPLOY_TIMEOUT_SECONDS` | `1200` | 单次维护最长秒数 |
| `ASTRA_REMOTE_GATEWAY_LOCAL_URL` | `http://127.0.0.1:8110` | SSH 反向隧道的本机中转入口 |
| `ASTRA_REMOTE_GATEWAY_PUBLIC_URL` | 空 | 配置后直接使用该中转地址 |

## 安装和配置范围

- root 用户自动安装系统依赖；非 root 用户必须已有必要系统工具、可用 Git，软件安装到用户目录，缺少管理员权限时明确失败。
- 支持 x86_64 / aarch64 的 Debian/Ubuntu、RHEL 系列。OpenCode 统一使用 `npm install --global --prefix "$HOME/.local/share/astra/npm" --registry <配置的镜像> --include=optional opencode-ai@<指定版本>` 安装，npm 验证包完整性，实际可执行版本必须匹配。仅验证成功后才将员工配置的执行路径链接到 npm 安装目录；旧的独立二进制即使版本相同，也会迁移到 npm 管理。已满足要求的 npm 安装会复用。
- 内嵌工作区前端同步到上游 `v1.18.33`，提供对应版本的静态资源；保留已发布的旧版本资源供历史 Session 使用。
- CentOS 7 使用独立 Vault repo 配置安装依赖，不改原 yum 源；旧 glibc x86_64 使用 Node glibc-217 构建、npm 包自动选择的 OpenCode 平台二进制和隔离的 Alpine musl/C++ 运行库。仅为 musl 加载器增加运行库路径，不替换系统 glibc。Git 低于 2.20 时编译 2.43.7。CentOS 7 已停止维护，建议后续迁移受维护系统。
- 工程目录为空时初始化 Git 和初始提交；非空且不是 Git 仓库时拒绝，已有仓库保留原内容。
- 在远端用户的 `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json` 合并 `astra-gateway` provider、默认模型和 `nexus-library` MCP。写入前备份为 `.astra-backup-<操作ID>`，配置及备份权限为 0600，其他 provider/MCP/字段保留。已有 JSONC 或无效 JSON 时拒绝覆盖，需人工合并。
- 同一 SSH 用户的全局配置对该用户的其他 OpenCode 工程也生效；需要独立配置时使用独立 Linux 账号。
- 平台 API 不回显 SSH 密码，维护日志隐藏服务密钥；远端全局配置含访问凭据，请保护该 Linux 账号和配置备份。

## 维护与恢复

部署或重启期间不能再次维护、修改或删除该员工、检测环境或启动任务。有占用任务、待确认提交、未结束 Runtime Session 或忙碌的原生 Session 时拒绝维护。重启只终止 PID、工程目录和 Serve 参数均匹配的原进程，端口冲突明确失败。

界面可取消操作；浏览器断线同样取消等待并关闭 SSH 连接。已执行的系统安装不会回滚，远端脚本还有超时和文件锁保护。失败或取消后先查看失败阶段再显式重试；服务进程崩溃遗留的操作租约到期后可重试。不要同时对同一 Linux 用户的多个员工部署。部署结束会检查 Serve、模型中转认证及图书馆 MCP，模型实际生成还取决于中转上游可用性。
