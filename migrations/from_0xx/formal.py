"""1.0 正式 schema 的离线导入适配；迁移账本仍在独立 SQLite 中。

目标事务原子提交。与离线账本之间不声称分布式 exactly-once：重跑核对整批哈希恢复。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections import Counter
from pathlib import Path
from uuid import uuid5

from sqlalchemy import Boolean, Integer, String, create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from domains.database import Base

from .etl import (
    NAMESPACE,
    MigrationError,
    _uuid,
    canonical,
    digest,
    load_bundle,
    utcnow,
    validate_plan,
    write_json,
)

SCHEMA_REVISION = "1002"
OLD_TABLES = {
    "digital_employees",
    "opencode_execution_environments",
    "runtime_sessions",
    "assistant_conversations",
}
SUPPORTED_KINDS = {
    "actors",
    "teams",
    "roles",
    "employees",
    "workers",
    "tasks",
    "task_executions",
    "knowledge_items",
    "historical_channels",
    "historical_messages",
    "historical_execution_subjects",
    "experience_evidence",
    "historical_archive",
}
ARCHIVE_ONLY = {"historical_execution_subjects", "experience_evidence", "historical_archive"}
INSERT_ORDER = [
    "actors",
    "teams",
    "roles",
    "employees",
    "team_members",
    "workers",
    "tasks",
    "channels",
    "channel_members",
    "messages",
    "knowledge_items",
    "task_executions",
    "historical_artifacts",
]


def _identifier(label: str, identifier: str) -> str:
    return str(uuid5(NAMESPACE, f"formal:{label}:{identifier}"))


def _target_engine(target_url: str):
    try:
        url = make_url(target_url)
        backend = url.get_backend_name()
        if backend == "sqlite":
            if not url.database or url.database == ":memory:":
                raise MigrationError("正式导入目标必须是已初始化的磁盘数据库")
            path = Path(url.database).resolve()
            if not path.is_file():
                raise MigrationError("目标数据库不存在；先在独立空库执行 1.0 schema 初始化")

            def connect():
                connection = sqlite3.connect(path, timeout=30)
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                return connection

            engine = create_engine("sqlite://", creator=connect)
            identity = {"dialect": "sqlite", "database": str(path)}
        elif backend == "mysql" and url.drivername not in {"mysql+asyncmy", "mysql+aiomysql"}:
            engine = create_engine(url, pool_pre_ping=True)
            identity = {"dialect": "mysql", "host": url.host, "port": url.port, "database": url.database}
        else:
            raise MigrationError("正式导入仅支持 SQLite 或同步 MySQL 驱动")
        return engine, digest(identity)
    except MigrationError:
        raise
    except Exception as error:
        raise MigrationError("目标连接初始化失败；请在安全环境检查驱动与连接配置") from error


def _assert_schema(connection) -> None:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    if tables & OLD_TABLES:
        raise MigrationError("目标含 0.xx 领域表，拒绝修改旧库")
    if tables != set(Base.metadata.tables) | {"alembic_version"}:
        raise MigrationError("目标不是完整且独立的当前 1.0 schema")
    revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if revisions != [SCHEMA_REVISION]:
        raise MigrationError("目标 Alembic revision 与导入适配版本不一致")
    for name, table in Base.metadata.tables.items():
        columns = {column["name"]: column for column in inspector.get_columns(name)}
        if set(columns) != set(table.columns.keys()):
            raise MigrationError("目标列与当前 1.0 数据字典不一致")
        if inspector.get_pk_constraint(name)["constrained_columns"] != [
            column.name for column in table.primary_key.columns
        ]:
            raise MigrationError("目标主键与当前 1.0 schema 不一致")
        for column in table.columns:
            reflected = columns[column.name]
            if bool(reflected["nullable"]) != column.nullable:
                raise MigrationError("目标非空约束与当前 1.0 schema 不一致")
            reflected_type = reflected["type"]
            same_type = reflected_type._type_affinity is column.type._type_affinity
            mysql_boolean = isinstance(column.type, Boolean) and isinstance(reflected_type, Integer)
            if not same_type and not mysql_boolean:
                raise MigrationError("目标字段类型与当前 1.0 schema 不一致")
            if isinstance(column.type, String) and reflected_type.length != column.type.length:
                raise MigrationError("目标字段长度与当前 1.0 schema 不一致")
        expected_fk = {
            (
                tuple(constraint.column_keys),
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in table.foreign_key_constraints
        }
        actual_fk = {
            (
                tuple(constraint["constrained_columns"]),
                constraint["referred_table"],
                tuple(constraint["referred_columns"]),
            )
            for constraint in inspector.get_foreign_keys(name)
        }
        if expected_fk != actual_fk:
            raise MigrationError("目标外键约束与当前 1.0 schema 不一致")


def _complete(table_name: str, values: dict) -> dict:
    table = Base.metadata.tables.get(table_name)
    if table is None:
        raise MigrationError("正式 schema 缺少历史只读承载表，停止导入")
    if set(values) != set(table.columns.keys()):
        raise MigrationError(f"{table_name} 字段映射不完整；须更新离线适配器")
    for column in table.columns:
        value = values[column.name]
        if value is None:
            if not column.nullable:
                raise MigrationError(f"{table_name}.{column.name} 缺少显式非空值")
            continue
        if isinstance(column.type, Boolean) and not isinstance(value, bool):
            raise MigrationError("布尔字段类型不匹配")
        if isinstance(column.type, Integer) and (not isinstance(value, int) or isinstance(value, bool)):
            raise MigrationError("整数字段类型不匹配")
        if isinstance(column.type, String):
            if not isinstance(value, str) or (column.type.length and len(value) > column.type.length):
                raise MigrationError("字符串字段类型或长度不匹配，禁止截断历史事实")
    _uuid(values["id"])
    return values


def prepare_formal(bundle: Path, plan: dict) -> dict:
    """显式映射每一正式列；没有映射的内容进入可核验历史归档，并阻止签收。"""
    manifest, source_rows = load_bundle(bundle)
    validate_plan(plan)
    if manifest["bundle_id"] != plan["source_bundle_id"]:
        raise MigrationError("正式导入产物与源导出包不一致")
    unsupported = sorted({record["kind"] for record in plan["records"]} - SUPPORTED_KINDS)
    if unsupported:
        raise MigrationError("映射产物含未支持的目标类型，禁止跳过后签收")
    if "historical_artifacts" not in Base.metadata.tables:
        raise MigrationError("正式 schema 尚未提供不可变历史归档索引")
    team_id, actor_id = _uuid(plan.get("archive_team_id")), _uuid(plan.get("migration_actor_id"))
    imported_at = plan.get("reviewed_at")
    if not isinstance(imported_at, int):
        raise MigrationError("正式导入需要明确的映射审核时间")
    original = {(table, row["source_id"]): row for table, rows in source_rows.items() for row in rows}
    actors = {record["id"]: record["data"] for record in plan["records"] if record["kind"] == "actors"}
    channels = {record["id"]: record for record in plan["records"] if record["kind"] == "historical_channels"}
    channel_by_source = {record["source"]["id"]: record for record in channels.values() if record["source"]}
    message_sequences = {}
    for channel_id in channels:
        messages = [
            record
            for record in plan["records"]
            if record["kind"] == "historical_messages" and record["data"].get("channel_id") == channel_id
        ]
        for index, record in enumerate(
            sorted(messages, key=lambda item: (item["data"].get("created_at") or imported_at, item["id"])),
            start=1,
        ):
            message_sequences[record["id"]] = index
    rows, artifacts, sources = [], {}, []
    seen = set()
    archive_only_tables = set()
    private_access_blockers = []

    def append(table_name: str, values: dict, source: dict | None):
        values = _complete(table_name, values)
        identity = (table_name, values["id"])
        if identity in seen:
            raise MigrationError("正式映射产生重复目标身份")
        seen.add(identity)
        rows.append({"table": table_name, "id": values["id"], "values": values, "source": source})

    for record in plan["records"]:
        kind, data, identifier, source = record["kind"], record["data"], record["id"], record["source"]
        common = {
            "id": identifier,
            "revision": data.get("revision") or 1,
            "created_at": data.get("created_at") if data.get("created_at") is not None else imported_at,
        }
        archive_ref = None
        if source:
            source_key = (source["table"], source["id"])
            if source_key not in original:
                raise MigrationError("目标对象无法回溯源导出行")
            if source_key in sources:
                raise MigrationError("源行被重复映射，禁止导入")
            sources.append(source_key)
            raw = original[source_key]
            content = {"data": raw["data"], "redactions": raw["redactions"]}
            content_hash = hashlib.sha256((canonical(content) + "\n").encode()).hexdigest()
            archive_ref = f"artifact://{content_hash}.json"
            artifacts[content_hash] = content
            private = source["table"].startswith("assistant_")
            owner = None
            if private:
                conversation_id = raw["data"].get("conversation_id")
                if source["table"] == "assistant_conversations":
                    conversation_id = source["id"]
                if source["table"] == "assistant_messages":
                    conversation_id = raw["data"].get("conversation_id")
                channel = channel_by_source.get(str(conversation_id))
                owner = channel["data"].get("owner_human_id") if channel else None
                if owner and (owner not in actors or actors[owner].get("kind") != "HUMAN"):
                    raise MigrationError("历史私聊所有人必须指向显式审核的 HUMAN Actor")
                if not owner:
                    private_access_blockers.append({"kind": kind, "id": identifier})
            append(
                "historical_artifacts",
                {
                    **common,
                    "id": _identifier("artifact", identifier),
                    "team_id": team_id,
                    "kind": {
                        "tasks": "TASK_SNAPSHOT",
                        "workers": "WORKER_CONFIGURATION",
                        "task_executions": "NATIVE_SESSION_SNAPSHOT",
                        "knowledge_items": "KNOWLEDGE_ARCHIVE",
                        "historical_channels": "CONVERSATION_ARCHIVE",
                        "historical_messages": "MESSAGE_ARCHIVE",
                        "historical_execution_subjects": "EXECUTION_IDENTITY",
                        "experience_evidence": "EVIDENCE_ARCHIVE",
                    }.get(kind, "SOURCE_ARCHIVE"),
                    "content_ref": archive_ref,
                    "sha256": content_hash,
                    "visibility": "PRIVATE" if private else "AUDIT",
                    "owner_actor_id": owner,
                    "read_only": True,
                },
                source,
            )
        if kind in ARCHIVE_ONLY:
            if not source:
                raise MigrationError("只读历史归档必须有真实来源行")
            archive_only_tables.add(source["table"])
            continue
        if kind == "actors":
            append(
                "actors",
                {**common, "kind": data["kind"], "name": data["name"], "permissions": [], "active": False},
                source,
            )
        elif kind == "teams":
            append(
                "teams",
                {**common, "name": data["name"], "denied_actions": data.get("denied_actions", [])},
                source,
            )
        elif kind == "roles":
            append(
                "roles",
                {
                    **common,
                    "team_id": data["team_id"],
                    "name": data["name"],
                    "mandate": data.get("mandate", ""),
                    "permissions": data.get("permissions", []),
                    "skill_scope": data.get("skill_scope", []),
                    "knowledge_scope": data.get("knowledge_scope", []),
                },
                source,
            )
        elif kind == "employees":
            if identifier not in actors or actors[identifier].get("kind") != "EMPLOYEE":
                raise MigrationError("员工候选必须配置同 UUID 的独立 EMPLOYEE Actor")
            append(
                "employees",
                {
                    **common,
                    "name": data["name"],
                    "team_id": data["team_id"],
                    "role_id": data["role_id"],
                    "manager_id": data["manager_id"],
                    "lifecycle": "PAUSED",
                    "scope": data.get("scope", {}),
                    "permissions": [],
                    "daily_token_budget": data.get("daily_token_budget", 0),
                },
                source,
            )
        elif kind == "workers":
            append(
                "workers",
                {
                    **common,
                    "name": data["name"],
                    "base_url": data.get("base_url"),
                    "runtime_version": data.get("runtime_version"),
                    "capabilities": data.get("capability_tags", []),
                    "allowed_projects": [],
                    "workspace_roots": data.get("workspace_roots", []),
                    "credential_ref": data.get("credential_ref"),
                    "health": "UNKNOWN",
                    "concurrent_slots": 0,
                    "enabled": False,
                    "last_seen_at": None,
                },
                source,
            )
        elif kind == "tasks":
            append(
                "tasks",
                {
                    **common,
                    "team_id": data["team_id"],
                    "owner_employee_id": data.get("owner_employee_id"),
                    "created_by_actor": actor_id,
                    "goal_id": None,
                    "source_event_id": None,
                    "title": data["title"],
                    "objective": data["objective"],
                    "acceptance_criteria": data["acceptance_criteria"],
                    "constraints": [],
                    "required_capabilities": [],
                    "asset_scope": {},
                    "status": data["status"],
                    "priority": 3,
                    "risk_level": "LOW",
                    "continuity_key": data["continuity_key"],
                    "parent_task_id": None,
                    "latest_result": None,
                    "read_only": True,
                    "completed_at": data.get("completed_at"),
                    "updated_at": imported_at,
                },
                source,
            )
        elif kind == "task_executions":
            append(
                "task_executions",
                {
                    **common,
                    "task_id": data["task_id"],
                    "worker_id": data["worker_id"],
                    "native_session_id": data["native_session_id"],
                    "workspace_ref": data.get("workspace_ref"),
                    "workspace_base_commit": None,
                    "preparation_started_at": None,
                    "submission_started_at": None,
                    "permission_digest": None,
                    "stop_requested": None,
                    "abort_started_at": None,
                    "attempt_no": data["attempt_no"],
                    "lease_id": None,
                    "lease_fence": None,
                    "grant_snapshot": {},
                    "state": "HISTORICAL",
                    "read_only": True,
                    "evidence_refs": [
                        {
                            "kind": "native_session",
                            "native_status": data.get("native_status"),
                            "archive_ref": archive_ref,
                            "requires_reconciliation": True,
                        }
                    ],
                    "output_ref": None,
                    "started_at": data.get("started_at"),
                    "finished_at": data.get("finished_at"),
                    "superseded_by": data.get("superseded_by"),
                },
                source,
            )
        elif kind == "knowledge_items":
            append(
                "knowledge_items",
                {
                    **common,
                    "team_id": data["team_id"],
                    "created_by_actor": actor_id,
                    "title": data["title"],
                    "kind": data["kind"],
                    "content": data["content"],
                    "source_refs": [*data.get("source_refs", []), {"artifact_ref": archive_ref}],
                    "verification": data["verification"],
                    "status": "ARCHIVED",
                },
                source,
            )
        elif kind == "historical_channels":
            append(
                "channels",
                {
                    **common,
                    "team_id": team_id,
                    "name": data["title"],
                    "kind": "ARCHIVE",
                    "dm_key": None,
                    "read_only": True,
                },
                source,
            )
            owner = data.get("owner_human_id")
            if owner:
                append(
                    "channel_members",
                    {
                        **common,
                        "id": _identifier("channel-member", identifier + owner),
                        "channel_id": identifier,
                        "actor_id": owner,
                    },
                    None,
                )
                member_id = _identifier("team-member", team_id + owner)
                if ("team_members", member_id) not in seen:
                    append(
                        "team_members",
                        {**common, "id": member_id, "team_id": team_id, "actor_id": owner, "role": "MEMBER"},
                        None,
                    )
        elif kind == "historical_messages":
            append(
                "messages",
                {
                    **common,
                    "channel_id": data["channel_id"],
                    "seq": message_sequences[identifier],
                    "sender_id": actor_id,
                    "content": data["content"],
                    "mentions": [],
                    "attachment_refs": [],
                    "reply_to": None,
                    "causal_root": "migration:" + identifier,
                    "hops": 0,
                    "fingerprint": digest(
                        {
                            "channel_id": data["channel_id"],
                            "content": data["content"],
                            "message_id": identifier,
                        }
                    ),
                    "provenance": {
                        "historical_speaker_role": data.get("historical_speaker_role"),
                        "imported_by_actor": actor_id,
                        "read_only": True,
                    },
                },
                source,
            )
    if set(sources) != set(original):
        raise MigrationError("映射未覆盖全部源行，禁止部分导入后签收")
    mapped = {(row["table"], row["id"]): row["values"] for row in rows}
    for row in rows:
        table = Base.metadata.tables[row["table"]]
        for foreign_key in table.foreign_keys:
            value = row["values"][foreign_key.parent.name]
            if value is not None and (foreign_key.column.table.name, value) not in mapped:
                raise MigrationError("正式目标外键缺少明确导入对象，禁止猜测或复用未知对象")
    rows.sort(key=lambda row: (INSERT_ORDER.index(row["table"]), row["id"]))
    prepared = {
        "source_bundle_id": plan["source_bundle_id"],
        "plan_id": plan["plan_id"],
        "rows": rows,
        "artifacts": artifacts,
        "schema_revision": SCHEMA_REVISION,
        "archive_only_source_tables": sorted(archive_only_tables),
        "private_access_blockers": private_access_blockers,
        "source_row_count": len(original),
        "external_references": plan["external_references"],
    }
    prepared["import_hash"] = digest(prepared)
    return prepared


def _ledger(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables and tables != {"formal_tool", "formal_batches", "formal_rows"}:
        connection.close()
        raise MigrationError("正式导入账本必须是独立工具文件")
    if tables:
        markers = [row[0] for row in connection.execute("SELECT name FROM formal_tool")]
        if markers != ["astra-formal-import-v1"]:
            connection.close()
            raise MigrationError("正式导入账本标记不匹配")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS formal_tool (name TEXT PRIMARY KEY);
        INSERT OR IGNORE INTO formal_tool VALUES ('astra-formal-import-v1');
        CREATE TABLE IF NOT EXISTS formal_batches (
            plan_id TEXT NOT NULL, target_hash TEXT NOT NULL, import_hash TEXT NOT NULL,
            state TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (plan_id, target_hash)
        );
        CREATE TABLE IF NOT EXISTS formal_rows (
            plan_id TEXT NOT NULL, target_hash TEXT NOT NULL, target_table TEXT NOT NULL,
            target_id TEXT NOT NULL, content_hash TEXT NOT NULL, source_json TEXT,
            PRIMARY KEY (plan_id, target_hash, target_table, target_id)
        );
    """)
    connection.commit()
    os.chmod(path, 0o600)
    return connection


def _artifact_files(root: Path, artifacts: dict) -> None:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for content_hash, content in artifacts.items():
        path = root / f"{content_hash}.json"
        if path.exists():
            if path.read_text(encoding="utf-8") != canonical(content) + "\n":
                raise MigrationError("历史归档文件内容发生差异，拒绝覆盖")
        else:
            write_json(path, content)


def _actual_rows(connection, rows: list[dict]) -> dict:
    result = {}
    for table_name in {row["table"] for row in rows}:
        table = Base.metadata.tables[table_name]
        for values in connection.execute(select(table)).mappings():
            result[(table_name, values["id"])] = dict(values)
    return result


def import_schema(
    bundle: Path,
    plan: dict,
    target_url: str,
    ledger_path: Path,
    artifact_root: Path,
    *,
    dry_run: bool = False,
    fail_after: int | None = None,
    fail_after_commit: bool = False,
) -> dict:
    prepared = prepare_formal(bundle, plan)
    engine, target_hash = _target_engine(target_url)
    ledger = None
    prior = None
    try:
        with engine.connect() as connection:
            _assert_schema(connection)
            connection.rollback()
        if dry_run:
            return {
                "dry_run": True,
                "schema_revision": SCHEMA_REVISION,
                "target_hash": target_hash,
                "expected_target_rows": len(prepared["rows"]),
                "cutover_allowed": False,
            }
        ledger = _ledger(ledger_path)
        with ledger:
            ledger.execute("BEGIN IMMEDIATE")
            prior = ledger.execute(
                "SELECT * FROM formal_batches WHERE plan_id=? AND target_hash=?",
                (plan["plan_id"], target_hash),
            ).fetchone()
            if prior and prior["import_hash"] != prepared["import_hash"]:
                raise MigrationError("原迁移批次字段映射已改变，禁止覆盖；请先保留差异与回滚方案")
            if not prior:
                ledger.execute(
                    "INSERT INTO formal_batches VALUES (?, ?, ?, 'PREPARED', ?)",
                    (plan["plan_id"], target_hash, prepared["import_hash"], utcnow()),
                )
                for row in prepared["rows"]:
                    ledger.execute(
                        "INSERT INTO formal_rows VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            plan["plan_id"],
                            target_hash,
                            row["table"],
                            row["id"],
                            digest(row["values"]),
                            canonical(row["source"]),
                        ),
                    )
        _artifact_files(artifact_root, prepared["artifacts"])
        inserted, recovered = 0, False
        with ledger:
            # 同账本的批次串行执行；目标数据库仍以自身事务/FK/唯一约束阻止并发双写。
            ledger.execute("BEGIN IMMEDIATE")
            with engine.connect() as connection:
                if engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                else:
                    connection.begin()
                try:
                    _assert_schema(connection)
                    actual = _actual_rows(connection, prepared["rows"])
                    expected = {(row["table"], row["id"]): row["values"] for row in prepared["rows"]}
                    present = set(actual) & set(expected)
                    if present:
                        if (
                            not prior
                            or present != set(expected)
                            or any(canonical(actual[key]) != canonical(expected[key]) for key in present)
                        ):
                            raise MigrationError("目标含不完整、外来或变化的同身份数据，拒绝部分覆盖")
                        recovered = True
                    else:
                        for table in Base.metadata.tables.values():
                            if connection.execute(select(table).limit(1)).first() is not None:
                                raise MigrationError("正式首次导入要求独立空 schema，目标已有业务事实")
                        deferred = []
                        for row in prepared["rows"]:
                            if fail_after is not None and inserted >= fail_after:
                                raise MigrationError("测试注入：正式导入中断，整个目标事务回滚")
                            values = dict(row["values"])
                            if row["table"] == "task_executions" and values["superseded_by"]:
                                deferred.append((row["id"], values.pop("superseded_by")))
                                values["superseded_by"] = None
                            connection.execute(Base.metadata.tables[row["table"]].insert().values(**values))
                            inserted += 1
                        executions = Base.metadata.tables["task_executions"]
                        for execution_id, superseded_by in deferred:
                            connection.execute(
                                executions.update()
                                .where(executions.c.id == execution_id)
                                .values(superseded_by=superseded_by)
                            )
                        actual_after = _actual_rows(connection, prepared["rows"])
                        if any(
                            canonical(actual_after.get(key)) != canonical(value)
                            for key, value in expected.items()
                        ):
                            raise MigrationError("目标写入内容与显式映射不一致，整个事务回滚")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            if fail_after_commit:
                raise MigrationError("测试注入：目标已提交但账本未签记，重跑需全量哈希恢复")
            ledger.execute(
                "UPDATE formal_batches SET state='COMMITTED',updated_at=? WHERE plan_id=? AND target_hash=?",
                (utcnow(), plan["plan_id"], target_hash),
            )
        return {
            "plan_id": plan["plan_id"],
            "import_hash": prepared["import_hash"],
            "target_hash": target_hash,
            "schema_revision": SCHEMA_REVISION,
            "inserted": inserted,
            "recovered": recovered,
            "table_counts": dict(Counter(row["table"] for row in prepared["rows"])),
            "source_rows_archived": prepared["source_row_count"],
            "formal_schema_imported": True,
            "archive_only_source_tables": prepared["archive_only_source_tables"],
            "private_access_blockers": prepared["private_access_blockers"],
            "signoff_blockers": [
                "真实外部 Session/Workspace/Skill/文件核验",
                "全量系统验收",
                "切换签收",
                *[f"仅归档未转正式领域：{name}" for name in prepared["archive_only_source_tables"]],
            ],
            "cutover_allowed": False,
        }
    except MigrationError:
        if ledger:
            with ledger:
                ledger.execute(
                    "UPDATE formal_batches SET state='FAILED_OR_UNCONFIRMED',updated_at=? "
                    "WHERE plan_id=? AND target_hash=?",
                    (utcnow(), plan["plan_id"], target_hash),
                )
        raise
    except Exception as error:
        if ledger:
            with ledger:
                ledger.execute(
                    "UPDATE formal_batches SET state='FAILED_OR_UNCONFIRMED',updated_at=? "
                    "WHERE plan_id=? AND target_hash=?",
                    (utcnow(), plan["plan_id"], target_hash),
                )
        raise MigrationError(
            "正式导入失败；目标事务已回滚或需按原产物核对提交状态，不公开驱动异常"
        ) from error
    finally:
        if ledger:
            ledger.close()
        engine.dispose()


def reconcile_schema(
    bundle: Path, plan: dict, target_url: str, ledger_path: Path, artifact_root: Path
) -> dict:
    """独立只读对账，不修改目标、账本或历史文件，也不产生切换签收。"""
    prepared = prepare_formal(bundle, plan)
    if not ledger_path.is_file():
        raise MigrationError("正式导入账本不存在")
    engine, target_hash = _target_engine(target_url)
    ledger = None
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
            else:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            _assert_schema(connection)
            actual = _actual_rows(connection, prepared["rows"])
            mismatches = [
                {"table": row["table"], "id": row["id"]}
                for row in prepared["rows"]
                if canonical(actual.get((row["table"], row["id"]))) != canonical(row["values"])
            ]
            connection.rollback()
        ledger = sqlite3.connect(ledger_path.resolve().as_uri() + "?mode=ro", uri=True)
        ledger.row_factory = sqlite3.Row
        batch = ledger.execute(
            "SELECT * FROM formal_batches WHERE plan_id=? AND target_hash=?", (plan["plan_id"], target_hash)
        ).fetchone()
        mapped = {
            (row["target_table"], row["target_id"]): row
            for row in ledger.execute(
                "SELECT * FROM formal_rows WHERE plan_id=? AND target_hash=?", (plan["plan_id"], target_hash)
            )
        }
        ledger_mismatches = []
        for row in prepared["rows"]:
            saved = mapped.get((row["table"], row["id"]))
            if (
                not saved
                or saved["content_hash"] != digest(row["values"])
                or saved["source_json"] != canonical(row["source"])
            ):
                ledger_mismatches.append({"table": row["table"], "id": row["id"]})
        file_mismatches = []
        for content_hash in prepared["artifacts"]:
            path = artifact_root / f"{content_hash}.json"
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != content_hash:
                file_mismatches.append({"sha256": content_hash})
        source_counts = Counter()
        for row in prepared["rows"]:
            if row["table"] == "historical_artifacts":
                source_counts[row["source"]["table"]] += 1
        passed = bool(
            batch
            and batch["state"] == "COMMITTED"
            and not (mismatches or ledger_mismatches or file_mismatches)
        )
        return {
            "generated_at": utcnow(),
            "plan_id": plan["plan_id"],
            "target_hash": target_hash,
            "schema_revision": SCHEMA_REVISION,
            "passed_formal_reconciliation": passed,
            "ledger_state": batch["state"] if batch else "MISSING",
            "source_archive_counts": dict(source_counts),
            "target_content_mismatches": mismatches,
            "ledger_mapping_mismatches": ledger_mismatches,
            "artifact_file_mismatches": file_mismatches,
            "archive_only_source_tables": prepared["archive_only_source_tables"],
            "private_access_blockers": prepared["private_access_blockers"],
            "external_references": prepared["external_references"],
            "cutover_allowed": False,
        }
    except MigrationError:
        raise
    except Exception as error:
        raise MigrationError("正式 schema 只读对账失败；不公开数据库或文件内容") from error
    finally:
        if ledger:
            ledger.close()
        engine.dispose()
