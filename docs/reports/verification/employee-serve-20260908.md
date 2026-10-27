# 数字员工独立 OpenCode Serve 验证

日期：2026-09-08

## 实现

- Coordinator 的 LOCAL Server 分支使用员工 workspace_root、opencode_path、opencode_server_port、model_name；启动、续聊、恢复查询均使用员工客户端。
- LOCAL Serve 监听 127.0.0.1，以员工工作空间作为 cwd 后台启动；任务完成不关闭服务。健康检查成功后复用；跨进程文件锁避免同端口重复启动。
- 复用前检查员工/工作空间归属记录及真实 `/path`，防止已健康的其他工作空间 Serve 被误用。
- 不健康的本 Worker 所启动进程可终止后重启；未知进程不直接终止，端口被占用时明确失败。启动失败、超时包含员工、环境、工作空间、端口、启动方式和日志路径，沿用 Coordinator 执行异常流程。
- 停止任务 API 根据任务环境快照连接员工端口，不再访问公共 Serve。
- Remote 保持 SSH loopback tunnel；异常时尝试重启 PID 文件指向且命令/cwd 匹配的服务，补充端口占用及启动日志诊断。
- 环境检测只探测 Serve，不启动；Serve 未启动不影响环境可用。Workspace 必须存在且可写。
- LOCAL/REMOTE 均显示人工端口字段和实际 Serve 地址。平台助手代码未修改。

## 配置注意

现存默认 4096 不自动改写，也不自动分配端口。LOCAL 员工须在配置页人工选择独立固定端口（例如 4101、4102），避开平台公共和助手端口，然后测试连接。同主机上的远程员工也须配置不同端口。更换 Serve 后，旧公共服务中的活跃 Session 应先停止并按现有重跑流程处理，不将旧公共服务作为回退路径。

## 证据

- 本机真实 OpenCode 1.18.29：固定端口 44101 和 44102 分别启动；`/global/health` 成功，`/path.directory` 分别为两个含中文和空格的临时工作空间；各创建独立 Session；重复 ensure_ready 后 PID 不变。测试创建的进程已停止，临时工作空间已清理。该验证未调用模型执行业务 Prompt。
- 专项后端测试覆盖：双员工真实 HTTP 子进程、健康复用、并发冷启动、异常重启、端口冲突、归属冲突、启动失败、启动超时、不存在的工作空间、环境检测不启动、Coordinator 客户端选择、停止接口端口路由及远程只读检测。
- 后端回归 122 passed / 1 deselected（工作空间严格存在检查前）；最终受影响模块专项 56 passed。
- 排除的是既有 `test_assistant_migration_adopts_complete_precreated_schema`：硬编码断言 head 为 0015，但本次开始时工作树已经存在 0016_category_prompts。未修改该不相关迁移或断言。首轮由此连带出现的分类/图书馆测试失败，在隔离复跑和排除此项后的全量回归中均通过。
- Ruff、git diff --check、Vue 类型检查、Vite 生产构建通过；构建保留既有大 chunk 提示。
- 远程启动命令通过 POSIX `sh -n` 语法验证，SSH/tunnel 流程通过测试替身验证。

## 尚未现场验证

真实 Linux SSH、Windows 进程行为、真实多 Worker 异常重启，以及模型业务任务端到端尚未在本轮验收。LOCAL Worker 重启后遗留的不健康未知进程会报告端口冲突，需要人工清理；不会仅凭 PID 或端口杀死未知进程。

本轮未提交、推送或部署；未改写现存员工配置。
