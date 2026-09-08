# Astra V0.4 操作使用指南

## 1. 平台用途

Astra 用于长期数字员工的任务分配、工作观察、人工介入和结果管理。

平台负责定义“做什么、谁来做、优先级和什么情况下算完成”。数字员工进入自己的工作空间后，由 Agent 自主决定如何阅读代码、调用 Skill / Tool、修改文件、运行命令和检查结果。

默认地址：

- 管理台：`http://localhost:5173`
- API 文档：`http://localhost:8100/docs`

## 2. 首次启动

Windows 公司电脑：

```powershell
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

首次安装会生成根目录 `.env`。填写 MySQL、Redis、OpenCode 和目录配置后执行：

```powershell
.\.venv\Scripts\python.exe .\scripts\preflight.py
```

开发环境：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev
```

正式环境：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro
```

查看、重启和停止：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev status
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev restart
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev stop
```

正式环境将 `dev` 替换为 `pro`。

Astra 不再维护独立的 bat / sh / PowerShell 启停脚本。`setup-windows.ps1` 只负责首次安装，`check-windows.ps1` 只负责诊断。

## 3. 推荐配置顺序

1. “配置中心 → 任务分类”检查业务分类。
2. “配置中心 → 员工配置”创建数字员工。
3. 配置员工支持的任务类型和任务分类。
4. 配置 Agent、模型、Workspace 和本地 / Linux 远程环境。
5. 保存并执行“测试连接”。
6. 按需开启自动领取和自主执行。
7. 创建第一项问题或需求任务。

员工状态和环境状态彼此独立。员工即使处于空闲，环境异常时也不会领取任务。

## 4. 任务分类

V0.4 默认提供：

- 测试平台
- 自动化工程
- 防线运营

管理员可新增、编辑、启用、停用和排序。

分类表示业务领域，不表示员工必须采用的技术步骤。

## 5. 数字员工配置

### 基本信息

- 员工 ID：创建后不可修改
- 员工名称
- 岗位与说明
- 启用状态

### 工作范围

工作范围只定义：

- 支持任务类型：问题、需求
- 支持任务分类

Skill、Tool、SubAgent、Commands 属于员工自己的 Agent 工作环境，不在 Astra 平台重复维护。

### 本地工作环境

需要配置：

- Agent 启动命令或绝对路径
- Agent 模型
- 长期 Workspace

Windows 路径可包含盘符、空格和中文目录。Astra 使用参数数组启动进程，不依赖 Bash。

### Linux 远程工作环境

还需要：

- Host / Port / Username
- SSH 密码
- 远程 Agent 路径
- 远程绝对 Workspace
- OpenCode Server Port

Astra 通过 Paramiko 连接远端，并通过 SSH Tunnel 访问只监听目标机 loopback 的 OpenCode Server。

平台不再提供 Linux Shell wrapper 模板。需要额外环境变量时，在目标主机配置 Agent 运行环境。

### 工作策略

- 自动领取任务
- 允许自主执行
- 最大自动重试次数

每名员工同时只处理一项任务。

## 6. 创建任务

进入“任务中心 → 创建任务”，填写：

- 标题
- 类型：问题 / 需求
- 分类
- 优先级
- 完成策略
- 描述
- 附件
- 验收标准
- 自动分配或指定员工

任务描述应说明业务背景、当前现象、目标、必要上下文和限制，不要把 Agent 必须执行的技术步骤固化成平台流程。

任务中不填写 Workspace、Skill、Tool、模型、执行命令或验证脚本。

## 7. 任务状态

常用状态：

- 待领取
- 处理中
- 等待人工
- 已挂起
- 待确认
- 已完成
- 未完成
- 执行异常
- 已取消

页面展示真实 Runtime 状态和工作记录，不展示虚构的固定阶段或进度百分比。

## 8. 任务详情

任务详情主要包含：

- 基本信息
- 任务描述和附件
- 验收标准
- 当前工作状态
- 工作记录
- 结果摘要
- 文件、提交、日志和产物
- Token / Tool / 运行时长
- Run 和执行环境

Astra 保存员工提交的处理结果，不运行独立 Verifier。

## 9. 待处理

“待处理”统一展示：

- 等待人工
- 已挂起
- 待确认
- 执行异常
- 无活动提示

员工需要人工输入时，应明确返回：

- 阻塞原因
- 已完成工作
- 当前状态
- 需要人工提供的具体内容

人工补充后，平台继续原执行会话，避免丢失上下文。

## 10. Run 与工作消耗

每次 Agent 执行形成一条 Run，记录：

- Task / Employee
- Session
- 环境快照
- 开始 / 结束时间
- Runtime 状态
- 模型
- Token
- Tool 调用

Token 只使用 Agent 事件中的真实数据，不根据字符数估算。没有返回的数据展示 `—`，与 `0` 含义不同。

## 11. 数字办公室

数字办公室反映员工当前真实工作状态：

- 工作中
- 空闲
- 等待人工
- 暂停
- 异常
- 离线

点击员工可查看当前任务、最近活动、工作时长、Token 和 Tool。

如需减少动画，前往“配置中心 → 系统设置 → 减少动效”。

## 12. Runtime

Astra 服务统一由：

```text
scripts/astra_service.py
```

管理。

开发：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py dev
```

正式：

```powershell
.\.venv\Scripts\python.exe .\scripts\astra_service.py pro
```

它统一管理：

- Backend
- Frontend
- Celery Beat
- Control Worker
- Agent Worker
- 员工 OpenCode Server
- 平台助手 OpenCode Server
- 可选 Library MCP

日志位于 `ASTRA_LOG_DIR`，PID 和启动模式位于 `ASTRA_RUNTIME_DIR/astra-service.json`。

## 13. 质量验证

完整验证：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify.py
```

单独 E2E：

```powershell
.\.venv\Scripts\python.exe .\scripts\e2e.py
```

质量门禁包含后端检查、后端测试、前端类型检查、生产构建和 Chromium E2E。

## 14. 常见问题

### 任务一直待领取

检查：

1. `astra_service.py <mode> status`
2. `runtime-beat.log`
3. `runtime-control.log`
4. `runtime-agent.log`
5. 员工是否启用
6. 环境是否正常
7. 任务类型和分类是否匹配

### Agent 环境异常

检查 Agent 可执行文件、版本、Workspace、模型和 OpenCode Server 端口。

### Linux 远程异常

重新执行“测试连接”，检查 SSH、远程 Workspace、OpenCode 路径和远程 Server Port。

### 验收项显示“无法确认”

表示员工最终回复没有返回可识别的逐项结论，不等同于任务失败。人工应结合任务结果和证据判断。
