# Astra V0.2 需求说明书

## 1. 版本目标

Astra V0.2 在 V0.1“数字员工自主领取任务并完成执行验证”的基础上，重点补齐两个能力：

1. **数字员工 OpenCode 执行环境配置**

   * 支持本地执行；
   * 支持 Linux 远程执行；
   * 不同数字员工可配置不同的 OpenCode 工作环境；
   * 支持多个数字员工分布在不同 Linux 环境中工作。

2. **数字员工工作消耗统计**

   * 统计每个员工的 Token 使用情况；
   * 统计每个任务的 Token 使用情况；
   * 统计 Tool 调用情况；
   * 在员工、任务和平台层面提供相应的数据展示。

V0.2 不建设独立的执行节点资源池，也不引入复杂的节点调度能力。

核心关系保持：

```text
任务
 ↓
数字员工
 ↓
员工自己的 OpenCode 执行环境
 ↓
OpenCode
 ↓
任务执行与验证
```

---

# 2. 版本定位

V0.1 解决：

> 数字员工是否可以在没有持续人工对话的情况下，自主发现任务、执行、验证并完成任务。

V0.2 进一步解决：

> 不同数字员工在哪里工作，以及如何观察每个员工真实消耗了多少模型和工具资源。

因此 V0.2 的重点不是增加更多 Agent 编排能力，而是完善数字员工自身的“工作环境”和“工作消耗”。

---

# 3. V0.2 核心概念

一个完整的数字员工由以下信息组成：

```text
Digital Employee
│
├── 基本身份
│
├── 岗位职责
│
├── 工作能力
│
├── OpenCode执行环境
│
├── 工作策略
│
└── 工作数据
```

其中：

### 基本身份

回答：

> 这个员工是谁？

包括：

* 员工名称；
* 员工 ID；
* 岗位；
* 描述；
* 状态。

### 工作能力

回答：

> 这个员工会做什么？

包括：

* Capability；
* Skill；
* 支持的任务类型；
* 支持的任务来源。

### OpenCode 执行环境

回答：

> 这个员工在哪里工作？

包括：

* 本地；
* Linux 远程。

### 工作策略

回答：

> 这个员工可以自主做到什么程度？

包括：

* 是否自动领取任务；
* 是否允许自动执行；
* 是否允许自动修复；
* 最大自动重试次数；
* 最大并发任务数。

### 工作数据

回答：

> 这个员工实际干了多少活、用了多少资源？

包括：

* 处理任务数；
* 自主完成率；
* 人工介入率；
* Token；
* Tool；
* 工作时长；
* 重试次数。

---

# 4. 数字员工 OpenCode 执行环境

## 4.1 基本要求

每个数字员工配置一个默认 OpenCode 执行环境。

V0.2 支持：

```text
LOCAL
LINUX_REMOTE
```

关系：

```text
DigitalEmployee
       │
       └── OpenCodeExecutionEnvironment
```

V0.2 不支持：

* 一个员工配置多个执行环境并动态调度；
* 环境池；
* 自动负载均衡；
* 自动容灾切换；
* Kubernetes；
* Docker 执行环境；
* 节点自动发现。

---

# 5. 本地执行环境

本地执行用于：

* Astra 开发；
* 功能快速验证；
* 单机部署；
* 本地数字员工运行。

定义：

> OpenCode 与 Astra 运行在同一台机器，由数字员工直接使用本机 OpenCode 环境工作。

员工配置展示：

```text
执行方式        本地执行

OpenCode路径     opencode
Workspace根目录  <本地路径>

环境状态        正常
```

本地执行环境需要支持：

* 检查 OpenCode 是否存在；
* 检查 OpenCode 是否可以正常启动；
* 检查 Workspace 是否可用；
* 测试环境配置。

---

# 6. Linux 远程执行环境

Linux 远程执行用于：

* 数字员工远程工作；
* 多台 Linux 服务器并行承载不同员工；
* 不同员工使用不同测试开发环境；
* 初步实现分布式数字员工执行。

关系示例：

```text
Astra-01
    ↓
本地 OpenCode

Astra-02
    ↓
Linux Server A
    ↓
OpenCode

Astra-03
    ↓
Linux Server B
    ↓
OpenCode
```

这就是 V0.2 的分布式执行形态。

不是：

```text
Task
 ↓
节点资源池
 ↓
自动选择服务器
```

而是：

```text
Task
 ↓
分配员工
 ↓
使用该员工配置的 OpenCode 环境
```

---

# 7. Linux 远程环境配置

员工配置中增加以下信息：

## 基础信息

```text
执行方式
Linux远程

环境名称
服务器名称

Host
SSH Port
Username

认证方式

OpenCode路径
Workspace根目录
```

可选展示：

```text
环境描述
标签
备注
```

---

# 8. 远程环境状态

员工的 OpenCode 环境需要具有明确状态。

建议：

```text
UNKNOWN
CHECKING
AVAILABLE
UNAVAILABLE
```

前端显示：

```text
● 正常
● 检查中
● 不可用
● 未检查
```

数字员工是否在线与 OpenCode 环境是否可用是两个不同概念。

例如：

```text
员工状态：IDLE
环境状态：UNAVAILABLE
```

表示员工本身处于启用状态，但当前无法正常工作。

---

# 9. 测试连接

员工配置页面必须提供：

```text
测试连接
```

本地模式至少检查：

* OpenCode 是否存在；
* OpenCode 是否可以正常执行；
* Workspace 是否可写。

Linux 模式至少检查：

* 远程环境是否可连接；
* 工作目录是否可用；
* OpenCode 是否存在；
* OpenCode 是否可以正常执行。

结果需要明确展示：

```text
连接成功
OpenCode 可用
Workspace 可用
```

或：

```text
连接失败
OpenCode 不存在
Workspace 无权限
```

不允许只返回“失败”而没有明确原因。

---

# 10. 员工创建与编辑页面

V0.2 将数字员工配置划分为四个区域。

---

## 10.1 基本信息

```text
员工名称
员工ID
岗位
描述
启用状态
```

---

## 10.2 工作能力

```text
支持任务来源
支持任务类型
Capabilities
Skills
最大并发数
```

---

## 10.3 OpenCode 执行环境

```text
执行方式
○ 本地
○ Linux远程
```

根据执行方式动态展示对应字段。

### 本地

```text
OpenCode路径
Workspace根目录
```

### Linux

```text
环境名称
Host
Port
Username
认证方式
OpenCode路径
Workspace根目录
```

操作：

```text
测试连接
```

---

## 10.4 工作策略

```text
自动领取任务
自动执行
自动修复
最大重试次数
最大并发数
```

V0.2 暂不增加复杂工作时间、值班时间和优先级策略。

---

# 11. 数字员工列表

数字员工列表增加：

```text
员工
岗位
状态
执行环境
当前任务
今日完成
今日Token
Tool调用
成功率
```

示例：

| 数字员工     | 状态   | OpenCode环境       | 当前任务     | 今日完成 | Token | Tool |
| -------- | ---- | ---------------- | -------- | ---: | ----: | ---: |
| Astra-01 | 工作中  | 本地               | TASK-001 |    5 |  1.8M |  236 |
| Astra-02 | 空闲   | Linux · server-a | -        |    8 |  2.4M |  318 |
| Astra-03 | 等待人工 | Linux · server-b | TASK-018 |    3 |  980K |  127 |

列表中应能够快速判断：

* 员工是否在线；
* 员工在哪里工作；
* 当前是否有任务；
* 今日主要工作量。

---

# 12. 数字员工详情页

V0.2 数字员工详情增加两个主要模块：

```text
运行环境
工作消耗
```

---

# 13. 员工运行环境展示

员工详情页展示：

```text
OpenCode执行环境
────────────────────

执行方式
本地 / Linux远程

环境名称

服务器
Host

OpenCode

Workspace

环境状态

最近检查时间
```

提供：

```text
测试连接
```

如果当前员工正在执行任务，同时展示：

```text
当前执行目录
当前 OpenCode Session
```

---

# 14. Token 使用统计

V0.2 需要统计 OpenCode 执行期间产生的模型 Token 使用。

至少包含：

```text
Input Tokens
Output Tokens
Cache Read Tokens
Cache Write Tokens
```

如果某类数据当前 OpenCode 不提供，则允许显示：

```text
-
```

但数据结构需要能够容纳。

另外展示：

```text
Total Tokens
```

Total Tokens 的计算口径需要在系统中保持一致。

---

# 15. Token 数据维度

Token 至少支持以下两个主要维度：

### 员工维度

例如：

```text
Astra-01

今日Token
本周Token
累计Token
平均每任务Token
```

### 任务维度

例如：

```text
TASK-001

Input
Output
Cache Read
Cache Write
Total
```

后续可扩展：

* 日；
* 周；
* 月；
* 自定义时间区间。

---

# 16. 员工详情中的 Token 展示

数字员工详情增加：

## 今日工作消耗

```text
今日 Token           2.48M
今日 Tool 调用         386
今日完成任务             8
今日运行时长          6h18m
```

Token 明细：

```text
Input         1.12M
Output         180K
Cache Read    1.18M
Cache Write      0
```

---

# 17. Token 趋势

员工详情支持展示：

```text
Token 使用趋势
```

至少支持：

```text
近7天
近30天
```

图表维度：

```text
Input
Output
Cache Read
```

V0.2 不要求复杂 Token 成本估算。

内部没有公开计费口径时，不显示金额。

---

# 18. Tool 调用统计

除 Token 外，需要统计数字员工调用的 Tool。

至少需要记录：

```text
Tool名称
调用次数
成功次数
失败次数
```

可进一步统计：

```text
调用耗时
```

---

# 19. Tool 分类

Tool 不要求在 V0.2 建立复杂分类体系。

前端按 OpenCode 实际返回名称展示即可，例如：

```text
Read
Edit
Write
Bash
Skill
MCP
SSH
其他
```

如果 Tool 名称更具体，可以保留原始名称。

---

# 20. Tool 使用展示

员工详情增加：

```text
工具调用 TOP
```

示例：

```text
Bash       96
Read       81
Edit       42
Skill      31
SSH        18
其他       27
```

同时展示：

```text
Tool总调用次数
Tool成功率
Tool失败次数
```

---

# 21. 任务详情工作消耗

任务详情增加：

```text
本任务工作消耗
```

展示：

```text
执行员工
OpenCode执行环境
模型

Input Tokens
Output Tokens
Cache Read Tokens
Cache Write Tokens
Total Tokens

LLM调用次数
Tool调用次数
执行时长
```

例如：

```text
执行员工          Astra-02
执行环境          Linux · server-a

Input             128K
Output             16K
Cache Read         320K
Total              464K

Tool调用             52
运行时长            28min
```

---

# 22. 任务 Tool 明细

任务详情支持查看本任务 Tool 使用情况。

展示：

| Tool  | 调用 | 成功 | 失败 |
| ----- | -: | -: | -: |
| Bash  | 18 | 17 |  1 |
| Read  | 14 | 14 |  0 |
| Edit  |  7 |  7 |  0 |
| Skill |  6 |  6 |  0 |
| SSH   |  7 |  7 |  0 |

V0.2 不要求展示每一次 Tool 调用的完整参数。

运行日志仍可作为详细排查入口。

---

# 23. Run 消耗

Token 与 Tool 统计首先归属于：

```text
Run
```

再汇总到：

```text
Task
Employee
Platform
```

逻辑关系：

```text
Employee
   │
   ├── Task
   │     │
   │     ├── Run 1
   │     ├── Run 2
   │     └── Run 3
   │
   └── Usage Summary
```

同一任务发生自动修复和重试时：

```text
任务总消耗
=
所有 Run 消耗合计
```

---

# 24. 运行记录页面

运行记录增加：

```text
执行员工
执行环境
Token
Tool调用
执行时长
结果
```

示例：

| Run     | Task     | 员工       | 环境      | Token | Tools |  耗时 | 结果   |
| ------- | -------- | -------- | ------- | ----: | ----: | --: | ---- |
| RUN-001 | TASK-001 | Astra-01 | Local   |  188K |    32 | 18m | PASS |
| RUN-002 | TASK-002 | Astra-02 | Linux-A |  326K |    51 | 31m | FAIL |

点击 Run 可查看详细使用情况。

---

# 25. 总览页面

总览页不增加过多复杂指标。

V0.2 在原指标基础上增加：

```text
今日 Token
今日 Tool 调用
```

数字员工卡可增加：

```text
今日：1.8M Token · 236 Tools
```

总览仍以：

* 谁在工作；
* 有多少任务；
* 有多少人工介入；
* 今天完成多少任务；

为主要信息。

Token 和 Tool 只是辅助运营指标。

---

# 26. 配置中心调整

V0.1 的独立员工配置能力，在 V0.2 中进一步完善。

配置中心包含：

```text
数字员工
任务源
系统设置
```

OpenCode 执行环境属于：

```text
数字员工配置
```

不单独建设：

```text
执行节点管理
```

---

# 27. 数字员工配置页面

建议布局：

```text
数字员工配置

左侧
员工列表

右侧
员工配置详情
```

右侧 Tab：

```text
基本信息
工作能力
执行环境
工作策略
```

其中 V0.2 重点是：

```text
执行环境
```

---

# 28. 执行环境显示要求

任何任务执行记录都必须能够明确回答：

```text
谁执行的？
在哪执行的？
使用哪个 OpenCode 环境？
```

因此任务和 Run 页面必须展示：

```text
employee
execution_environment
workspace
opencode_session
```

方便问题追踪。

---

# 29. 执行环境与任务的关系

任务不直接选择执行机器。

任务只选择或自动匹配：

```text
数字员工
```

然后使用：

```text
该员工当前配置的 OpenCode 执行环境
```

关系：

```text
Task
 ↓
Employee
 ↓
OpenCodeExecutionEnvironment
```

这是 V0.2 必须坚持的产品模型。

---

# 30. 员工环境修改

员工配置允许修改 OpenCode 执行环境。

如果员工当前：

```text
IDLE
```

允许直接修改。

如果员工：

```text
WORKING
```

前端需要明确提示：

> 当前员工存在运行中的任务，执行环境修改仅对后续任务生效。

不能改变正在执行任务的实际运行环境信息。

当前 Run 必须保留运行时的环境快照。

---

# 31. 环境快照

任务开始执行时，需要保存当时使用的执行环境信息。

目的：

即使后续管理员修改：

```text
Astra-02
Linux-A → Linux-B
```

历史任务仍显示：

```text
TASK-001
运行环境：Linux-A
```

不能随着员工当前配置变化而改变历史记录。

---

# 32. Token / Tool 数据口径

Token 和 Tool 数据来源必须基于 OpenCode 实际执行信息。

不允许通过模型自行估算。

例如不能：

```text
LLM认为本次用了约100K Token
```

必须使用 OpenCode 实际暴露的数据。

如果当前内部 OpenCode 某些数据无法获取：

```text
明确标记不可获取
```

不能伪造或推算。

---

# 33. Token 异常情况

需要考虑：

```text
任务中止
OpenCode异常退出
员工被暂停
任务转人工
执行失败
```

即使任务没有完成，已经产生的 Token 和 Tool 使用量仍需要保留。

例如：

```text
TASK-001
状态：FAILED

Token：168K
Tool：36
```

工作消耗不依赖任务最终成功。

---

# 34. 人工介入后的消耗

任务进入：

```text
WAIT_HUMAN
```

之后人工补充信息并继续执行。

后续 OpenCode Resume 产生的 Token / Tool：

继续归入同一个 Task。

如果产生新的 Run：

```text
Task
├── Run 1
└── Run 2
```

任务层统一汇总。

---

# 35. 员工绩效展示调整

V0.2 员工绩效信息建议分为两组。

### 工作结果

```text
完成任务数
自主完成率
人工介入率
任务通过率
平均重试次数
平均任务耗时
```

### 工作消耗

```text
Token
Tool调用
工作时长
平均每任务Token
平均每任务Tool调用
```

不要直接将：

```text
Token越少
```

定义为员工表现越好。

Token / Tool 首先属于运营观察数据，不直接作为绩效结论。

---

# 36. 页面调整范围

V0.2 需要更新以下页面：

```text
总览
数字员工列表
数字员工详情
任务详情
运行记录
数字员工配置
```

---

# 37. 总览新增内容

新增：

```text
今日 Token
今日 Tool 调用
```

员工卡增加轻量消耗信息。

不增加复杂分析面板。

---

# 38. 数字员工列表新增内容

增加：

```text
执行环境
今日Token
Tool调用
```

支持通过状态筛选：

```text
本地
Linux远程
环境异常
```

---

# 39. 数字员工详情新增内容

增加：

```text
运行环境
工作消耗
Token趋势
Tool调用TOP
```

当前任务仍保持核心位置。

---

# 40. 任务详情新增内容

增加：

```text
执行环境
任务Token
Tool调用
运行时长
```

Tool 明细支持展开查看。

---

# 41. 运行记录新增内容

增加：

```text
执行环境
Token
Tools
```

用于定位某次运行的资源使用情况。

---

# 42. 数字员工配置新增内容

增加：

```text
OpenCode执行环境
```

支持：

```text
本地
Linux远程
```

并提供：

```text
测试连接
```

---

# 43. V0.2 不包含

本版本明确不建设：

```text
Docker执行环境
Kubernetes
执行节点资源池
节点自动注册
Node Scheduler
负载均衡
任务自动跨机器迁移
失败节点自动接管
一员工多执行环境
多环境自动选择
GPU资源调度
Temporal
复杂Agent编排
多Agent协同
模型API接入
Token成本计费
员工绩效自动评分
```

---

# 44. V0.2 验收场景一：本地员工

配置：

```text
Astra-01

执行方式：
本地

OpenCode：
本地OpenCode
```

创建或发现任务后：

```text
TASK-001
 ↓
Astra-01
 ↓
本地OpenCode
 ↓
完成任务
```

系统能够查看：

```text
Token
Tool调用
运行时长
结果
```

---

# 45. V0.2 验收场景二：Linux 远程员工

配置：

```text
Astra-02

执行方式：
Linux远程

环境：
Linux Server A
```

测试连接成功。

任务：

```text
TASK-002
 ↓
Astra-02
 ↓
Linux Server A
 ↓
OpenCode
 ↓
执行完成
```

任务详情明确展示：

```text
执行员工：Astra-02
执行环境：Linux Server A
```

以及实际 Token、Tool 使用情况。

---

# 46. V0.2 验收场景三：多员工分布式工作

存在：

```text
Astra-01 → Local
Astra-02 → Linux-A
Astra-03 → Linux-B
```

分别领取不同任务：

```text
TASK-001 → Astra-01
TASK-002 → Astra-02
TASK-003 → Astra-03
```

三个员工可以使用各自 OpenCode 环境独立工作。

管理平台能够同时查看三名员工状态、当前任务、执行环境和工作消耗。

V0.2 不要求平台动态选择 Linux-A / Linux-B。

---

# 47. V0.2 验收场景四：工作消耗统计

任意任务完成后，应可以查看：

```text
Input Tokens
Output Tokens
Cache Read Tokens
Cache Write Tokens
Total Tokens

Tool调用总数
Tool类型分布

运行时长
```

数字员工详情能够汇总该员工所有任务数据。

---

# 48. V0.2 核心验收标准

V0.2 完成后，Astra 必须能够回答以下问题：

### 员工

```text
Astra-02现在是否在工作？
正在做什么任务？
```

### 环境

```text
Astra-02在哪里工作？
使用哪套OpenCode环境？
环境现在是否可用？
```

### 执行

```text
TASK-002是谁完成的？
在哪台机器完成的？
```

### 消耗

```text
TASK-002用了多少Token？
调用了多少次Tool？
主要调用了哪些Tool？
```

### 员工运营

```text
Astra-02今天完成了多少任务？
用了多少Token？
进行了多少次Tool调用？
自主完成率是多少？
```

---

# 49. V0.2 最终目标

Astra V0.2 不追求复杂资源调度。

本版本重点让数字员工进一步具备“真实员工”的两个属性：

## 有自己的工作环境

```text
Astra-01
在本地工作

Astra-02
在Linux-A工作

Astra-03
在Linux-B工作
```

## 工作过程可以被度量

```text
做了多少任务
花了多少时间
用了多少Token
调用了多少Tool
是否自主完成
```

最终形成：

```text
任务
 ↓
数字员工
 ↓
员工专属OpenCode执行环境
 ↓
自主工作
 ↓
执行验证
 ↓
工作结果
 +
工作消耗
```

V0.2 的核心不是“管理服务器”，而是：

> **让每个数字员工拥有明确的 OpenCode 工作环境，并能够观察这个员工真实的工作过程和资源消耗。**
