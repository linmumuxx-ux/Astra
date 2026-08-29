# Astra V0.4 操作使用指南

## 1. 平台用途

Astra 用于长期数字员工的任务分配、工作观察、人工介入和结果管理。

平台负责定义“做什么、为什么做、谁来做、重要程度以及什么情况下算完成”。数字员工进入自己的工作空间后，由其 Agent 自主决定阅读代码、调用 Skill 或 Tool、修改文件、运行命令和检查结果的方式。当前内置 OpenCode 适配器，后续可接入 Claude Code、Codex 等 Agent 工具。

默认地址：

- 本地管理台：`http://localhost:5173`
- API 文档：`http://localhost:8100/docs`

## 2. 首次启动

公司 Windows 电脑推荐使用 PowerShell 快速安装。脚本会依次查找已有虚拟环境、`ASTRA_PYTHON` 指定路径、`py.exe -3.11` 和 `python.exe`，并输出实际 Python 版本：

```powershell
git clone git@github.com:linxuyiyi/Astra.git
cd Astra
powershell -ExecutionPolicy Bypass -File .\scripts\setup-windows.ps1
```

首次安装会从 `deploy\astra.env.windows.example` 生成根目录 `.env`。填写 MySQL、Redis、Agent 可执行文件和目录后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start-windows.ps1
```

停止平台：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stop-windows.ps1
```

Python 3.8 不属于当前支持范围，后端基线为 Python 3.11+。

Linux 开发环境可手动启动：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload --port 8100
```

另开一个终端启动任务调度运行时：

```bash
./scripts/runtime.sh
```

这个常驻进程包含 Celery Worker 与 Beat，并连接 Redis。Beat 定期领取任务，Worker 调用员工配置的 Agent 执行器；它未运行时，管理台和 API 虽然可以打开，新任务却不会离开“待领取”。本地默认 Redis 未运行时，脚本会尝试启动临时 Redis，并在退出时一并关闭。

再开一个终端：

```bash
cd frontend
npm ci
npm run dev
```

开发环境默认生成演示数据。正式环境必须设置 `ASTRA_SEED_DEMO=false`。

## 3. 推荐配置顺序

1. 在“配置中心 → 任务分类”检查或补充业务分类。
2. 在“配置中心 → 员工配置”创建数字员工。
3. 为员工选择支持的任务类型和任务分类。
4. 配置员工本地或 Linux 远程工作环境，以及该员工长期使用的工程工作空间。
5. 保存环境配置；平台会自动检测，确认环境状态为“正常”。也可随时手动点击“测试连接”。
6. 配置自动领取、允许自主执行和最大自动重试次数。
7. 创建第一项“问题”或“需求”任务，填写验收标准并自动分配或指定员工。

员工状态和环境状态彼此独立。例如，员工可以处于“空闲”，环境同时处于“异常”；此时员工不会自动领取任务。

## 4. 配置任务分类

V0.4 默认提供：

- 测试平台；
- 自动化工程；
- 防线运营。

管理员可新增、编辑、启用、停用和调整排序。停用分类不会删除历史任务，但不能再用于创建新任务或新增员工工作范围。

分类表示业务领域，不表示员工需要使用的技术或执行步骤。

## 5. 配置数字员工

### 基本信息

- 员工 ID：创建后不可修改，建议使用稳定标识，例如 `astra-04`。
- 员工名称：页面展示名称。
- 岗位与说明：描述职责和业务边界。
- 启用状态：停用后不再分配新任务，历史记录和用量继续保留。

### 工作范围

工作范围只包含：

- 支持任务类型：问题、需求；
- 支持任务分类：从配置中心已启用分类中选择。

Astra 不在员工配置中维护 Skills、Capabilities、Commands、Tools 或 SubAgents。这些属于员工自己的 Agent 工作环境。

### 工作环境

每名员工配置一个 Agent 工作环境。当前版本内置 OpenCode 适配器；页面以中性的 Agent 环境和执行会话描述平台能力。

本地环境需要：

- 环境名称；
- Agent 启动命令或绝对路径（当前适配器填写 `opencode`）；
- Agent 模型，例如 `deepseek/deepseek-v4-flash`；留空时使用 Agent 自身配置或平台默认模型；
- 员工工作空间，例如 Windows 的 `D:\code\nr_test_system`，或 Linux 的 `/srv/projects/nr_test_system`。

Windows 路径可包含盘符、空格和中文目录。Agent 可执行文件可填写 PATH 中的命令名，也可填写 `C:\Program Files\OpenCode\opencode.exe` 之类的完整路径；Astra 使用参数数组启动进程，不要求 Bash，也不需要手工给路径加 Shell 转义。

Linux 远程环境还需要：

- Host、Port、Username；
- SSH 密码；已配置的密码不会回显，编辑时留空表示保持不变；
- 远程 Agent 启动命令或路径；
- 远程绝对工作空间。

“测试连接”会分别检查 Agent 启动命令是否存在、是否可启动、工作空间是否存在且可写；远程环境还会通过 Paramiko 检查 SSH 连接。员工 SSH 密码以明文保存在部署数据库中，API 只返回是否已配置，不回显密码，也不会把密码写入任务快照、运行记录或证据。该模式只适用于受控公司内网，数据库和备份必须限制访问。

如果实际 Agent 命令依赖配置目录或安全检查开关，可参考 `deploy/start-agent.windows.bat.example` 与 `deploy/start-agent.linux.sh.example` 创建机器本地启动器，再把 `opencode_path` 指向启动器。Windows `.bat` 的注释保持英文，避免 cmd.exe 以非 UTF-8 代码页误解析中文注释。

修改“Agent 模型”并保存后，配置中心会重新检测环境。新领取的任务会把该模型写入环境快照并在每次 Run 中记录实际模型。为兼容升级前已经领取但尚未完成的任务，缺少模型字段的旧快照会继承员工当前配置；已经带模型的新快照保持领取时的值。

工作空间属于员工并在不同任务间长期复用。任务不会再创建自己的源码副本，也不会保存工程路径。

### 工作策略

- 自动领取任务：空闲且环境正常时领取类型和分类匹配的任务。
- 允许自主执行：领取后启动该任务独立的执行会话。
- 最大自动重试次数：Agent 执行异常时允许恢复同一任务会话的次数。

V0.4 固定每名员工同时只处理一项任务。

## 6. 创建任务

进入“任务中心”，点击“创建任务”，填写：

- 任务标题；
- 任务类型：问题或需求；
- 任务分类；
- 优先级：很高、高、中、低；
- 完成策略：自动完成或需人工确认；
- 任务描述；
- 可选附件；
- 一项或多项验收标准；
- 自动分配或指定员工。

优先级提示：

- 很高：重要且紧急；
- 高：重要但可以计划处理；
- 中：有一定影响或时效要求；
- 低：一般优化或可延期事项。

任务描述可自然说明背景、当前情况、问题现象、需要实现的能力、必要上下文和已知限制。不要把员工必须执行的技术步骤写成平台流程。

创建任务页面不会出现工程路径、Workspace、执行会话、Skill、Tool、模型、执行命令或验证脚本。

## 7. 任务状态

- 待领取：等待自动领取或已指定员工但尚未启动；
- 处理中：员工正在自己的工作空间处理任务；
- 等待人工：员工缺少信息、权限、判断或外部依赖；
- 已挂起：工作现场已保留且员工已释放；
- 待确认：员工已提交结果，等待人工签收或退回；
- 已完成：员工结果已按完成策略生效；
- 未完成：员工无法完成任务并提交原因；
- 执行异常：Agent、SSH、环境或平台运行中断，等待恢复；
- 已取消：任务被人工取消。

页面只显示状态、员工实际工作进展和运行时长，不显示固定任务阶段或推测的进度百分比。

## 8. 任务详情

任务详情依次展示：

- 基本信息：类型、分类、优先级、状态、执行员工与时间；
- 任务描述与附件；
- 验收标准及员工逐项提交的满足、未满足或无法确认结果；
- 当前工作状态；
- 按时间排列的工作记录；
- 结果摘要、主要修改、关联文件、关联提交、日志和其他产物；
- Token、Tool 和运行时长；
- 执行会话、执行环境与 Run 记录。

Astra 保存员工提交的结果，不运行独立 Verifier，也不会因平台自定义测试命令决定任务是否完成。

## 9. 待处理

进入“待处理”可统一查看等待人工、已挂起、待确认、执行异常和无活动提示。人工协助请求包含：

- 阻塞原因；
- 已经完成的工作；
- 当前状态；
- 需要人工提供的内容。

处理人可以补充信息并继续任务，或终止任务。继续后沿用该任务原执行会话，避免丢失上下文。

### 询问场景

当任务必须先询问使用者时，员工应返回一个可直接回答的具体问题。任务进入“等待人工”，页面同时保留阻塞原因、已完成工作、当前现场和问题原文。处理人在“待处理”中填写答案并点“补充并继续”，Worker 会把答案带回原执行会话；员工完成后再逐项提交验收结果。该链路已纳入系统级 E2E，不需要使用者手工替平台验证。

## 10. 数字员工与运行记录

数字员工列表展示岗位、状态、工作范围、工作环境、当前任务、今日完成、今日 Token 和工具调用。员工详情进一步展示当前工作、环境检查、今日工作情况、近 7/30 天 Token 趋势、工具调用 Top 和历史任务。

每次 Agent 执行形成一条 Run，记录：

- Task 与 Employee；
- 执行会话；
- 执行环境快照；
- 开始和结束时间；
- 运行状态；
- 模型与 Token；
- Tool 名称、调用、成功、失败和耗时。

Run 不记录 Astra 自定义业务阶段。

## 11. 工作消耗口径

- Token 只取 Agent JSON 事件中的实际字段，不根据字符数估算。
- 至少记录 Input、Output、Cache Read、Cache Write 与 Total Token。
- 工具调用保留 Agent 返回的真实工具名称。
- 数据首先归属 Run，再汇总到 Task、Employee 和 Platform。
- 未完成、已取消或等待人工的任务，其已经产生的 Token、Tool 和运行时长继续保留。
- Agent 没有返回的数据显示 `—`，与数值 `0` 含义不同。
- V0.4 不展示费用，不把 Token 或 Tool 用量转换成员工评分或排名。

## V0.4 连续工作操作

### 数字办公室

“总览”和“数字员工”页默认展示数字办公室。工位直接反映工作中、空闲、等待人工、暂停、异常和离线状态。点击工位会在页内展开当前任务、进展、最近活动、工作时长、Token 和 Tool，并可继续进入员工或任务详情。在“数字员工”页可切换回表格视图。

如需禁用工作动画，前往“配置中心 → 系统设置 → 减少动效”。

### 任务队列和自动领取

员工完成当前任务后回到空闲，分配器会继续领取下一项匹配任务。顺序为：

1. 显式指定给该员工的任务；
2. 优先级从很高到低；
3. 同优先级按创建时间先到先得。

在员工详情的“员工任务队列”可查看当前任务和后续队列。

### 安全挂起与恢复

- “等待人工”表示员工仍占用该任务，人工补充后继续原 Session。
- “已挂起”表示已保留任务、Session、当前进展和现场上下文，同时释放员工。
- 在任务详情点“安全挂起”；后续在任务详情或“待处理”中点“继续任务”。挂起任务会回到原员工队列。

### 结果确认

创建任务时可选“自动完成”或“需人工确认”。很高和高优先级默认需人工确认，中和低默认自动完成。

待确认任务在“待处理”中可：

- 确认完成：签收员工结果；
- 退回继续：填写意见，任务回到原员工队列，继续原 Session。历史提交和退回意见均会保留。

### 执行异常和无活动

Agent、SSH、工作环境或平台重启导致中断时，任务先进入“执行异常”，不直接判为“未完成”。请先在员工详情重新“测试连接”，然后在“待处理”点“恢复执行”。

“长时间无新活动”只是提示。它不会自动改变任务状态，也不会把任务判为失败。

### 三层工作记录

任务详情中依次查看：

1. “工作进展”：面向管理者的可读时间线；
2. “详细操作”：Agent 工具与模型用量事件；
3. “运行记录”：原始 Run、Agent JSON 记录和附件证据。

Astra 不使用另一个模型概括员工工作，也不展示模型内部推理。

## 12. 接入任务来源

`nr_test_system` 可通过环境变量配置：

```bash
ASTRA_NR_TEST_SYSTEM_ENDPOINT=https://nr-test.example.internal
ASTRA_NR_TEST_SYSTEM_DISCOVER_PATH=/api/astra/tasks
ASTRA_NR_TEST_SYSTEM_RESULT_PATH=/api/astra/tasks/{external_task_id}/result
ASTRA_NR_TEST_SYSTEM_TOKEN=replace-with-secret
```

外部任务应映射为问题或需求、一个有效分类、中文优先级和验收标准。Task Scout 使用 `source + external_task_id` 幂等去重。

## 13. 常见问题

- 任务一直待领取：Windows 先运行 `scripts\check-windows.ps1`，再用 `scripts\process_manager.py status` 检查调度运行时；Linux 检查 `./scripts/runtime.sh` 或 systemd 服务。随后检查员工是否启用、空闲、允许自动领取，工作环境是否正常，以及类型和分类是否匹配。
- 启动后只有 traceback：先运行环境自检。每个失败项都会显示“检查项、当前值、失败原因、建议处理方式”，重点处理 MySQL、Redis、Agent、Workspace 和日志目录。
- 本地环境异常：以 Worker 账号执行配置的 Agent 命令加 `--version`，并检查员工工作空间是否存在且可写。
- Linux 远程环境异常：重新输入并保存 SSH 密码，检查网络、Host、Port、账号、远程 Agent 启动器和工作空间权限。
- Token 显示 `—`：当前 Agent 事件未提供该字段，Astra 不做估算。
- 任务等待人工：进入“待处理”查看完整阻塞说明，补充信息后继续同一 Session。
- 验收项显示“无法确认”：表示员工最终回复里没有可识别的该项结论，不等于执行失败或“未满足”。请结合工作记录人工判断；新运行会要求员工回传结构化逐项结论，并兼容清晰的 Markdown 验收表。
- 自动分配没有候选人：至少启用一名同时支持该任务类型和任务分类、环境正常且空闲的员工。

## 14. 验证与自检

代码升级或修改配置后，应让前后端来自同一个版本，再执行全量质量门禁：

```bash
./scripts/verify.sh
```

该命令会使用隔离的临时数据库与端口依次运行后端检查、后端测试、前端类型检查、生产构建和 10 条 Chromium E2E，不会写入日常开发数据库。E2E 会启动隔离 Redis 与真实 Celery Worker/Beat，并覆盖员工模型配置、配置保存、自动领取、结构化询问、人工回复、原会话继续和最终验收。

公司电脑在启动前或修改环境配置后运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-windows.ps1
```

自检会确认操作系统、Python 版本、依赖、MySQL 连接、迁移版本、数据表、Redis、默认 Agent、观察记录目录、日志目录与运行目录。MySQL 正式联调必须在能访问公司实例的机器上执行；SQLite 只用于本地开发和隔离测试。

需要验证 Astra 到真实本地 OpenCode 的简单闭环时运行：

```bash
.venv/bin/python scripts/real_opencode_smoke.py \
  --model deepseek/deepseek-v4-flash \
  --opencode "$(command -v opencode)"
```

脚本会在 Astra 仓库内临时创建员工工作空间和 SQLite 数据库，通过真实 `TaskCoordinator` 让 OpenCode 写入一个固定验收文件，并校验 Task、Run、Session、Token、Tool 和产物。工作空间位于仓库内是为了满足 OpenCode 的目录权限边界；成功后自动删除，失败时保留路径用于排查。该命令会真实调用模型并消耗 Token，运行前应确认本机 OpenCode 已登录且有权使用指定模型。

当前通过结果和已知环境边界见 `docs/verification/E2E-V0.4-2026-08-28.md`。

## 15. 版本边界

- Astra 不是 Coding Agent、工作流编排器、测试流程引擎、Skill 管理平台或 Tool 管理平台。
- 不提供一名员工多个并行工作空间、Git Worktree 调度、节点资源池或动态故障迁移。
- 员工 SSH 密码会保存在部署数据库中但不会经 API 回显或进入任务记录；任务源令牌和其他秘密仍必须通过受保护配置注入。
- 管理台没有内置登录/RBAC，必须部署在可信内网或企业认证网关之后。
- Celery 官方不承诺 Windows 支持；仓库的 Windows 启动器使用 `solo` 池规避多进程差异，但正式上线前仍需在公司 Windows 镜像上做稳定性验收。要求严格运行保障时，可把调度运行时部署到 Linux，并继续从 Windows 使用管理台。
