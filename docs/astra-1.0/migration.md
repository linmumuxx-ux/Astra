# 0.xx 一次性迁移

本文对应产品设计第 14 节。实现位于 `migrations/from_0xx/`，不引用旧 `backend/app`，也不被 1.0 的 API、领域服务或 Worker Runtime 引用。

当前实现支持只读导出、显式映射、隔离 staging 排练，以及已支持领域对象的正式 1.0 schema 原子导入、失败恢复和独立只读对账。每条源记录都会生成不可变历史文件和正式 `HistoricalArtifact` 索引。**没有执行真实旧库迁移或生产切换；所有报告仍返回 `cutover_allowed: false`。** 正式导入的 `formal_schema_imported: true` 只表示指定目标已写入支持的领域对象；未支持的类型只读归档并列入签收阻断项。测试中的 SQLite 数据为隔离夹具，不能替代真实历史签收。

## 产物与单一事实来源

| 产物 | 内容 | 用途 |
| --- | --- | --- |
| 冻结声明 | 确认人、冻结时间、安全备份引用、停止写入声明、在途执行处理方式 | 运营人员对真实冻结的签认；工具不代替停服务 |
| `manifest.json` | 固定源 commit、源数据库类型、每表主键/字段/FK、行数、脱敏数量、JSONL SHA256、bundle ID | 导出包完整性校验 |
| 每表 JSONL | 稳定源主键、脱敏后的完整源行、脱敏字段路径 | 离线事实快照；原始执行消息仍属于 OpenCode |
| 映射配置 | 审核人/时间、迁移 SYSTEM 主体、新组织、岗位/员工候选、Worker 配置、任务主责、状态、历史 DM 所有人 | 明确业务语义，不能由旧员工名称推断授权 |
| 映射产物 | `kind/id/data/source`、源 FK 清单、悬空关系、外部引用清单、plan ID | portable 目标，不是正式 ORM 的直接 insert 参数 |
| staging SQLite | `migration_batches`、`migration_records`、`migration_manifest`、专用工具标记 | 工具专属账本；不得挂到 1.0 业务库 |
| 正式导入账本 SQLite | `formal_batches`、`formal_rows`、工具标记，旧源 ID→新实体/历史索引映射与内容哈希 | 与正式业务库完全分离；支持跨提交窗口恢复 |
| 历史归档文件与索引 | 每条源行的脱敏 JSON、文件 SHA256、`artifact://<sha256>.json` 引用、正式 HistoricalArtifact | 可信只读历史内容；业务字段没有旧对象 ID |
| 对账报告 | 逐类行数、源主键一一映射、目标内容哈希、源引用、未验证外部引用、未完成门禁 | 审核与补齐；不得将 `passed_staging` 当切换许可 |

旧任务编号和旧员工编号只出现在离线源文件、映射配置和迁移账本。新对象 ID 使用稳定 UUIDv5；源数据不变且 namespace 不变时重跑 ID 不变。新 Task 的 `continuity_key` 使用新 UUID，创建主体为显式配置的 SYSTEM Actor，不能冒认旧人或新员工。

## 映射规则

- `opencode_execution_environments` 转为待配置 Worker：保留 host、工作区根与能力标签；OpenCode 版本必须由审核配置填写，不能猜测。导入候选默认 `enabled=false`、`health=UNKNOWN`、零可用槽，须完成真实环境验证与凭据重配。
- `digital_employees` 归档为历史执行主体；姓名/岗位等保留为候选材料。新业务 Employee 只由 `employees` 显式列出，默认待配置，不自动激活或赋权。原执行员工到 Worker 的关联只供历史执行归属。
- Task 主责只由 `task_owners` 指定；未指定为 `null`，所有历史任务 `read_only=true`。`task_status_map` 必须覆盖每个实际旧状态，缺失即停止。`completed_at` 仅读取旧同名完成事实，不以 `finished_at`、Session 状态或事件推断。
- RuntimeSession 转为只读执行候选，保留原生 Session ID、Workspace、原记录状态、终态原因与 `superseded_by`；旧任务的成功不会把 UNKNOWN Session 改成成功。所有 Session 都要求真实对账；工具不会重跑、续跑或补造执行结果。
- Knowledge 保留文档内容及验证状态，缺失状态为 `UNKNOWN`；导入为归档、要求发布复核，不将未知历史自动发布。Experience evidence、知识关系/来源/审核、Gateway 和其他表全部保留；没有正式领域映射的表进入只读历史档案候选，不静默丢弃。
- Assistant DM 转为只读历史 Channel，历史原文索引为 PRIVATE。所有人只接受 `human_assignments` 对审核 HUMAN Actor 的可信映射；映射后生成该所有人的成员关系，但迁入 Actor 仍 inactive，不创建登录凭据。未映射内容没有成员授权，列入签收阻断项。正式 Message 的 sender 为迁移 SYSTEM，`provenance` 保留原发言角色，不伪造新员工发言。
- 源 FK 按原表/列逐条核对，悬空关联阻止 staging 导入。源表没有主键时停止，必须先制定稳定身份快照策略，不能按导出顺序假造永久来源。

## 操作流程

从仓库根目录运行。使用包含 SQLAlchemy 的 Python；现有 `backend/.venv/bin/python` 可用于排练。离线工具未打包进正式应用 wheel，迁移时保留独立工具目录。

1. 在维护窗口备份旧库与必要文件，验证备份可恢复。停止旧 API 写入、Celery、Scout 与所有外部写入者；清点在途任务，排空或记录未知副作用，不能默认完成。复制 `freeze.example.json`，填写真实签认后才将 `legacy_writers_stopped` 设为 `true`。工具只校验声明，不执行停服务。
2. 通过安全环境变量配置旧库只读连接。SQLite 在驱动级使用 `mode=ro` 和 `PRAGMA query_only`，MySQL 使用只读、REPEATABLE READ、一致快照事务。生产 MySQL 还必须使用数据库侧仅 SELECT/元数据读取权限的独立账号。不要把带密码 URL 写入命令参数、文档、报告或聊天。
3. 先 dry-run 确认表/行数，再导出到全新目录。dry-run 不生成导出文件。

```bash
backend/.venv/bin/python -m migrations.from_0xx export \
  --freeze /secure/migration/freeze.json \
  --source-commit 05dd73142b294a9cb6b2b14a0750b707422aeec3 \
  --output /secure/migration/export-001 --dry-run

backend/.venv/bin/python -m migrations.from_0xx export \
  --freeze /secure/migration/freeze.json \
  --source-commit 05dd73142b294a9cb6b2b14a0750b707422aeec3 \
  --output /secure/migration/export-001
```

默认读取 `ASTRA_0XX_DATABASE_URL`；`--source-env` 可指定变量名称。SQLite URL 指向已存在磁盘文件。MySQL 使用同步 SQLAlchemy 驱动，例如 `mysql+pymysql`，须在隔离迁移环境安装驱动；当前环境没有 PyMySQL，也未运行真实 MySQL 验证。不能把正式运行用的 asyncmy URL 直接用于同步离线工具。

4. 复制 `mapping.example.json`，由业务与运维共同审核。示例的 `task_status_map` 故意为空，不能未经审核直接导入。`workers` 以旧环境 ID 字符串为键，正式导入必须明确提供 `base_url`，不能以 SSH host 猜测 OpenCode 地址；还可包含新 UUID、实测 `runtime_version`、`credential_ref`。凭据引用只允许无明文秘密的 `vault://` 或 `secret-ref://`。`task_owners` 以旧任务 ID 为键，值必须指向审核配置里的新 Employee UUID。`actors` 明确列出历史 Human 与新员工 Actor；Employee 必须配置同 UUID 的 EMPLOYEE Actor、Role、Team、manager。`human_assignments` 表达历史私聊权属签认，不创建登录凭据。

```bash
backend/.venv/bin/python -m migrations.from_0xx map \
  --bundle /secure/migration/export-001 \
  --mapping /secure/migration/mapping-reviewed.json \
  --output /secure/migration/plan-001.json

backend/.venv/bin/python -m migrations.from_0xx import-staging \
  --plan /secure/migration/plan-001.json \
  --staging /secure/migration/staging.sqlite --dry-run

backend/.venv/bin/python -m migrations.from_0xx import-staging \
  --plan /secure/migration/plan-001.json \
  --staging /secure/migration/staging.sqlite

backend/.venv/bin/python -m migrations.from_0xx reconcile \
  --bundle /secure/migration/export-001 \
  --plan /secure/migration/plan-001.json \
  --staging /secure/migration/staging.sqlite \
  --output /secure/migration/reconciliation-001.json
```

5. 审核 `class_counts`、`source_identity_match`、`content_hash_mismatches`、`dangling_references` 与外部引用清单。staging 数据与目标 SHA256 全部一致时 `passed_staging=true`，仍不得切换。

映射产物和导出包拒绝覆盖。导入每行连同来源映射在短事务里提交；进程中断或失败时批次标记 FAILED。使用原 `plan-001.json` 重跑会校验已有内容并跳过一致行，继续剩余行。映射变更或已有目标内容不同会拒绝覆盖；先保留差异证据，显式回滚原批次后才重新排练。

```bash
backend/.venv/bin/python -m migrations.from_0xx rollback-staging \
  --plan-id REPLACE_WITH_PLAN_SHA256 \
  --staging /secure/migration/staging.sqlite
```

回滚只删除该 plan 写入的 staging 行与映射，保留 ROLLED_BACK 批次记录；不修改源库、原导出文件或其他批次。工具拒绝把已有业务表的 SQLite 当 staging。

## 正式 1.0 schema 导入与对账

staging 是可选排练步骤，正式导入使用 `formal.py` 中的显式适配。先在独立空库执行 `migrations/schema/` 初始化；目标必须含当前所有新表、准确列/类型/长度/主键/FK 和 Alembic revision `1002`。存在旧领域表、缺表、额外业务表、revision 不符或已有业务事实时均拒绝首次导入。工具不会创建、升级或覆盖目标 schema。

通过安全环境配置 `ASTRA_1_0_MIGRATION_TARGET_URL`，使用同步 SQLite/MySQL 驱动。正式业务库、旧库、staging 和正式导入账本必须为不同文件/schema。

```bash
backend/.venv/bin/python -m migrations.from_0xx import-schema \
  --bundle /secure/migration/export-001 \
  --plan /secure/migration/plan-001.json \
  --ledger /secure/migration/formal-ledger.sqlite \
  --artifact-root /secure/migration/history \
  --output /secure/migration/formal-import-001.json --dry-run

backend/.venv/bin/python -m migrations.from_0xx import-schema \
  --bundle /secure/migration/export-001 \
  --plan /secure/migration/plan-001.json \
  --ledger /secure/migration/formal-ledger.sqlite \
  --artifact-root /secure/migration/history \
  --output /secure/migration/formal-import-001.json

backend/.venv/bin/python -m migrations.from_0xx reconcile-schema \
  --bundle /secure/migration/export-001 \
  --plan /secure/migration/plan-001.json \
  --ledger /secure/migration/formal-ledger.sqlite \
  --artifact-root /secure/migration/history \
  --output /secure/migration/formal-reconciliation-001.json
```

正式支持 Actor、Team、Role、Employee、Worker、Task、TaskExecution、Knowledge、历史 Channel/Message，以及派生成员关系与历史索引。只读历史 TaskExecution 的 lease/fence 均为空，不伪造新派工；原生状态保存在 evidence 索引与历史文件中，执行记录标记 HISTORICAL，不能恢复为可执行任务。候选 Employee 为 PAUSED，所有迁入 Actor 均 inactive 且没有运行权限/凭据；新 Worker disabled、零槽、UNKNOWN。后续启用须通过正常组织/身份/资源授权流程。

每条源行均写入一个 SHA256 命名的脱敏 JSON 文件，SHA256 对完整 UTF-8 文件字节计算（含末尾换行）；数据库只存引用与哈希。原来源 ID 只存在工具账本及只读内容文件，不进入新领域列。历史助手内容为 PRIVATE，其他默认 AUDIT。正式 API 读取 `artifact://` 时须使用受控 `ASTRA_V1_HISTORY_ARTIFACT_ROOT` 并核验文件哈希，禁止接受任意主机文件路径。实际根目录配置由部署维护人员签认。

正式写入按外键顺序在一个目标事务中完成；`superseded_by` 在全部 Session 索引插入后同事务回填。任意失败都回滚目标整批；已生成的不可变归档文件可保留重用。离线账本和目标库没有分布式事务：若目标已提交但账本未签记，重跑相同产物时必须全批 ID/内容哈希一致才能补记，不能补写一半或覆盖变化。目标事实已变化、归档文件被篡改或映射字段发生差异时停止，并要求人工审查。

`reconcile-schema` 只读比较正式目标每列内容、离线来源映射与文件字节哈希；`passed_formal_reconciliation=true` 不等于全量切换验收。旧员工、Experience evidence、Gateway 与缺乏正式业务适配的其他类型仍只读归档，并明确列入 `archive_only_source_tables`/`signoff_blockers`。未知 portable kind 直接拒绝整包导入，不允许静默跳过。成功后的业务库不提供泛化删除回滚；正式切换前需要恢复时使用已核验备份或重新初始化独立目标库，不能删除已产生的新业务事实。

## 凭据与历史文件

导出器移除 SSH 密码、API key/密文密钥材料、Authorization、私钥、token/digest 等结构化字段，同时清理文本中的已知 Bearer/API key/密码/URL 用户信息模式；保留脱敏路径与数量，不生成密钥哈希。二进制只记录长度与安全备份转移要求。原始秘密只经既有安全部署/备份渠道迁移，不能放入 JSONL、CSV、对话或日志。

自由文本可能包含无固定格式的秘密，自动规则不能证明内容绝无秘密。真实导出须在隔离环境完成组织级秘密扫描及人工签认后才可分发；工具产物默认限制文件权限，目录/备份的组织 ACL 由操作人员配置。扫描与签认目前未在真实数据执行。

外部 Workspace、原生 Session、证据 URI 与知识文件只形成 `UNCHECKED` 清单，**当前工具仅生成数据库源行归档，不复制外部执行/知识资产、不调用 Runtime，也不验证外部存在性**。真实签收必须逐个验证 Session 与工作区绑定、基线 commit、证据文件/内容哈希、Wiki 版本、Skill 来源/版本/验证状态；不可达对象应保留只读归档与明确失败原因。Session/Tool 消息不能转换成新社会对话。Skill 文件系统资产尚需独立 inventory/安全传输与版本对账适配。

## 真实切换前仍需完成

已支持对象通过正式 schema 的逐列映射承载历史完成事实、只读执行、知识原验证状态与 DM 权属，禁止直接 unpack portable 数据为 ORM 参数。未支持业务对象的纯归档、外部文件/Skill 正式版本迁移与原生执行核验仍需补齐；只读历史可查询不等于可恢复执行。

必须先在新空库执行正式 schema 初始化，完成生产源全量导出、领域导入、每类行数/关系/内容与外部证据核验、安全凭据重配、权限/多员工/并行/审批/恢复/SSE/前端等全量验收并签收。之后在维护窗口切换到 1.0 单运行树，归档旧代码与备份，删除旧运行实现。以上均未由本工具执行；在完成前不能勾选 OpenSpec `5.2`、`5.3` 或标记 Astra 1.0 完成。

## 已执行验证

`backend/.venv/bin/python -m pytest -q tests/v1/test_migration_etl.py tests/v1/test_migration_formal.py`：27 项隔离 SQLite 测试通过，覆盖只读导出/无凭据、冻结拒绝、显式员工/主责、UNKNOWN 终态不猜测、历史私聊隔离、staging 失败恢复/幂等/回滚/并发、正式新 schema 全 FK 导入、无伪造 Lease、历史文件 SHA256、正式整批回滚、目标已提交/账本未签记恢复、篡改拒绝、独立只读正式对账及旧库误写防护。另运行迁移目录与测试 Ruff 检查通过。

真实 MySQL、真实旧库、Session/Workspace/Skill 资产、生产 schema 数据导入、公司环境部署与生产切换：未验证。正式 schema importer 已在隔离 SQLite 实际执行并对账，但不是生产迁移报告。
