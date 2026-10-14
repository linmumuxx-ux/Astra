## ADDED Requirements

### Requirement: 节点、资源池、路由和密钥管理
控制面 MUST 随 Astra 管理台直接提供节点、资源池、模型路由与 Gateway Key 管理，不要求独立登录、管理 Token 或角色。控制面 MUST 加密保存下游凭据，只保存 Gateway Key 摘要，并且只在创建时返回 Key 原文。

#### Scenario: Create node and Key
- **WHEN** 使用者在 Astra 管理台创建节点或 Key
- **THEN** credentials are persisted securely, the response omits downstream secrets, and the Key plaintext is returned once

#### Scenario: 无管理凭据直接访问
- **WHEN** 使用者打开 API 中转管理页，或不携带管理凭据调用控制面查询与写接口
- **THEN** 管理页直接加载数据，接口按业务校验执行操作，不要求登录或管理角色

#### Scenario: 删除独立管理会话
- **WHEN** 使用者进入 API 中转或刷新管理页
- **THEN** 页面不显示管理凭据输入、管理身份或退出入口，不读写控制面会话凭据，也不请求管理权限接口

#### Scenario: 启动不要求管理凭据
- **WHEN** 生产环境已配置主密钥与 Redis，但未提供独立管理凭据
- **THEN** API 中转通过生产依赖校验并可启动

#### Scenario: Delete active node
- **WHEN** a node still accepts or serves requests
- **THEN** deletion is rejected until it has drained and active concurrency is zero

### Requirement: 三维节点状态与探测
The control plane MUST represent configuration, health and scheduling states independently. It MUST support network, service and model/streaming probes and record timing, outcomes and success/failure streaks.

#### Scenario: New node
- **WHEN** a node has not passed the required probe sequence
- **THEN** it remains unschedulable with UNKNOWN health

#### Scenario: New node defaults to a safe state
- **WHEN** an administrator creates a node without explicitly choosing scheduling and configuration states
- **THEN** it is created DRAINING and DISABLED with UNKNOWN health, and cannot become ACTIVE without a completed probe (no implicit ACTIVE default)

#### Scenario: 连接修改后重新探测
- **WHEN** 使用者保存节点连接字段的修改（地址、凭据、模型或健康路径）
- **THEN** 新连接的健康为 UNKNOWN，重新通过完整探测前不能被调度；旧请求及旧探测结果不能为新连接提供健康授权

#### Scenario: Probe failures and recovery
- **WHEN** a node fails three successive checks or later passes two successive checks
- **THEN** health changes to UNHEALTHY or HEALTHY respectively without changing its administrator configuration state

### Requirement: 保存后自动生效
配置表 MUST 是节点、资源池、模型路由与 Gateway Key 的唯一配置事实源。控制面 MUST 在保存时校验参数、引用和业务约束；保存成功后，各 Gateway 实例 MUST 在配置刷新周期内自动读取完整一致的配置并原子替换内存视图，不要求使用者管理草稿、发布、版本历史、回滚或对账。

#### Scenario: 保存配置
- **WHEN** 使用者成功保存节点、资源池、路由或 Key 的修改
- **THEN** Gateway 在配置刷新周期内自动采用新配置，无需手动发布；新建 Key 可以直接用于模型调用

#### Scenario: 保存非法配置
- **WHEN** 使用者保存不存在的资源池引用、非法连接参数或重复模型路由
- **THEN** 保存被拒绝，库中的有效配置不变

#### Scenario: 停用资源池
- **WHEN** 使用者停用仍被路由引用的资源池
- **THEN** 保存成功，新配置生效后停止向该池调度新请求，已有请求继续完成

#### Scenario: 配置刷新失败与恢复
- **WHEN** Gateway 读取配置失败或无法构建完整视图，之后数据库恢复
- **THEN** 失败期间保留最近有效的内存配置，后台继续重试，并在恢复后采用最新保存配置；首次启动且无有效配置时不能向下游转发

#### Scenario: 重启与多个实例
- **WHEN** Gateway 重启，或多个实例在配置保存后分别刷新
- **THEN** 各实例从配置表读取同一完整配置，不依赖历史版本或 Redis 发布状态

#### Scenario: 更新期间已有请求
- **WHEN** 配置被刷新且已有请求或流正在执行
- **THEN** 旧请求继续使用其原有完整配置，新请求使用刷新后的完整配置，不读取混合状态

#### Scenario: 删除版本接口
- **WHEN** 使用者打开管理台或请求旧草稿、版本、发布、回滚、对账接口
- **THEN** 管理台不提供配置版本页面，旧接口不可用

### Requirement: 吊销立即阻断
控制面 MUST 让已吊销的 Gateway Key 立即在所有数据面实例失效，不等待配置刷新。控制面 MUST 在提交数据库吊销前追加共享阻断状态；共享写入失败时 MUST 返回结构化 503 且不声称成功。已吊销 Key 的数据库记录和吊销时间 MUST 保留，不能因普通编辑而复活。

#### Scenario: 吊销尚未刷新到数据面的 Key
- **WHEN** 使用者吊销一个数据面当前内存配置仍标记为启用的 Key
- **THEN** 各实例立即拒绝该 Key 的新请求，不等待配置刷新

#### Scenario: Shared revocation write fails
- **WHEN** the shared revocation state cannot be written (for example Redis is unavailable)
- **THEN** the revoke request fails with a structured 503, the database revocation is not committed, and the response never claims success

#### Scenario: 编辑不能复活已吊销 Key
- **WHEN** 使用者编辑已吊销 Key 或尝试重新启用它
- **THEN** 该 Key 仍保持已吊销状态，数据面继续拒绝调用

### Requirement: 吊销状态的持久就绪
The shared revocation state MUST be append-only: synchronization MUST NOT clear existing entries or overwrite a concurrent revocation. Readiness MUST be a sentinel member inside the same revocation set, never a separate key, so that a Redis maxmemory eviction of the set removes the readiness sentinel together with the digests instead of leaving a false positive. Because Redis can be flushed or restarted, the data plane MUST append-sync all revoked Key digests from the database at startup and periodically, and mark the set ready in the same single `SADD` only after that sync. While the sentinel is missing or the shared state is unavailable, the data plane MUST fail closed. The data plane MUST read the sentinel and the digests as members of that one set in a single atomic operation; a missing sentinel MUST make that read itself fail closed, so a flush or whole-key eviction can never let a request through.

#### Scenario: Redis flushed or restarted
- **WHEN** the shared revocation set is lost, dropping the readiness sentinel together with every digest
- **THEN** new requests are rejected until a database sync rebuilds the set and its sentinel

#### Scenario: Revocation set key evicted
- **WHEN** Redis evicts the single revocation set key under maxmemory pressure
- **THEN** the sentinel disappears with the digests, so the atomic read fails closed and new requests are rejected until a database sync rebuilds the set; no request is authorized against an empty set

#### Scenario: Sentinel lost between independent reads
- **WHEN** the revocation set is flushed while a request is being authorized
- **THEN** the single atomic read fails closed and the request is rejected, never observing a present sentinel together with an empty set

#### Scenario: Concurrent synchronization and revocation
- **WHEN** synchronization runs while a revocation is being written concurrently
- **THEN** both previously revoked and concurrently revoked digests remain blocked

### Requirement: 操作审计
每项管理写操作 MUST 记录来源、时间、操作、结果与脱敏前后值，不保存秘密原文。新操作的来源 MUST 标记为 Astra 系统，不将浏览器提交的身份或角色作为已验证的个人身份；历史审计记录 MUST 保留。

#### Scenario: Update a node credential
- **WHEN** an administrator replaces a node credential
- **THEN** audit history identifies the change and never reveals either credential

#### Scenario: 浏览器身份不能伪造审计来源
- **WHEN** 使用者通过控制面提交写操作，并携带自定义身份或角色 Header
- **THEN** 操作记录仍使用 Astra 系统来源，不记录该 Header 为操作人
