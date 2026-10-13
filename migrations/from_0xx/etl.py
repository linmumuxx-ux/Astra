"""只读导出、显式领域映射和隔离 staging 账本。

staging 不是 1.0 数据库。本工具不会停止服务、调用 OpenCode、重跑任务或切换生产。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.engine import make_url

FORMAT_VERSION = 1
NAMESPACE = UUID("67447fbc-9ff2-5c4f-9948-9cc52d6518c1")
REDACTED = "[REDACTED: secure credential transfer required]"
SECRET_FIELD = re.compile(
    r"password|secret|api[_-]?key|private[_-]?key|authorization|"
    r"access[_-]?token|refresh[_-]?token|key_digest|key_prefix|credential|_encrypted$",
    re.IGNORECASE,
)
SECRET_TEXT = (
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(?:password|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(?<=://)[^\s/:]+:[^\s/@]+@"),
)
EXTERNAL_FIELDS = {
    "workspace": "workspace",
    "source_path": "file",
    "file_path": "file",
    "uri": "evidence",
    "source_uri": "evidence",
    "current_session_id": "native_session",
    "source_session_id": "native_session",
    "opencode_session_id": "native_session",
}


class MigrationError(Exception):
    """仅携带可公开的诊断，不拼接源数据库异常或凭据。"""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def sanitize(value: Any, path: str = "") -> tuple[Any, list[str]]:
    """移除结构化凭据及已知文本密钥；不生成可离线猜测密钥的哈希。"""
    redactions: list[str] = []
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if SECRET_FIELD.search(str(key)) or str(key).lower() == "token":
                if item not in (None, "", [], {}):
                    redactions.append(child)
                result[key] = None if item is None else REDACTED
            else:
                result[key], found = sanitize(item, child)
                redactions.extend(found)
        return result, redactions
    if isinstance(value, (list, tuple)):
        result = []
        for index, item in enumerate(value):
            cleaned, found = sanitize(item, f"{path}[{index}]")
            result.append(cleaned)
            redactions.extend(found)
        return result, redactions
    if isinstance(value, str):
        result = value
        for pattern in SECRET_TEXT:
            result = pattern.sub(REDACTED, result)
        return result, [path] if result != value else []
    if isinstance(value, (datetime, date)):
        return value.isoformat(), []
    if isinstance(value, bytes):
        # 二进制可能包含凭据；原始二进制由安全备份渠道保管。
        return {"binary_bytes": len(value), "transfer": "secure-backup"}, [path]
    if value is None or isinstance(value, (bool, int, float)):
        return value, []
    return str(value), []


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise MigrationError("JSON 文件无法读取或格式无效") from error


def write_json(path: Path, value: Any) -> None:
    """同目录原子替换，不把失败中间文件暴露为完整产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".astra-migration-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(canonical(value) + "\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_freeze(freeze: dict) -> None:
    required = ("frozen_at", "confirmed_by", "backup_ref", "in_flight_policy")
    if not all(freeze.get(key) for key in required):
        raise MigrationError("冻结声明缺少时间、确认人、备份引用或在途任务处理方式")
    if freeze.get("legacy_writers_stopped") is not True:
        raise MigrationError("必须显式确认旧 API/Celery/Scout/外部写入已停止")
    _seconds(freeze["frozen_at"])
    if sanitize(freeze)[1]:
        raise MigrationError("冻结声明含疑似明文凭据，请使用安全存储引用")


def _source_engine(source_url: str):
    try:
        url = make_url(source_url)
        if url.get_backend_name() == "sqlite":
            if not url.database or url.database == ":memory:":
                raise MigrationError("源 SQLite 必须是已存在的磁盘数据库")
            source_path = Path(url.database).resolve()
            if not source_path.is_file():
                raise MigrationError("源 SQLite 文件不存在")
            uri = source_path.as_uri() + "?mode=ro"

            def connect():
                connection = sqlite3.connect(uri, uri=True)
                connection.execute("PRAGMA query_only=ON")
                return connection

            return create_engine("sqlite://", creator=connect)
        if url.get_backend_name() != "mysql":
            raise MigrationError("只支持 SQLite 或 MySQL 只读源")
        if url.drivername in {"mysql+asyncmy", "mysql+aiomysql"}:
            raise MigrationError("离线工具需要同步 MySQL 驱动（例如 mysql+pymysql）")
        return create_engine(url, pool_pre_ping=True)
    except MigrationError:
        raise
    except Exception as error:
        raise MigrationError("无法初始化只读源连接；请检查驱动及安全环境变量") from error


def _row_id(data: dict, primary_key: list[str]) -> str:
    if not primary_key:
        raise MigrationError("源表无主键，无法保证重跑与逐行追溯；请先制定显式快照策略")
    values = [data[key] for key in primary_key]
    return str(values[0]) if len(values) == 1 else canonical(values)


def export_bundle(
    source_url: str,
    output: Path,
    freeze: dict,
    source_commit: str,
    *,
    dry_run: bool = False,
) -> dict:
    """在数据库只读事务内反射全部表，不 import 旧 ORM。"""
    validate_freeze(freeze)
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise MigrationError("source_commit 必须是固定的完整 Git commit")
    if output.exists() and not dry_run:
        raise MigrationError("导出目录已存在；请使用新目录，禁止覆盖审计证据")
    engine = _source_engine(source_url)
    temporary: Path | None = None
    try:
        if not dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".astra-export-", dir=output.parent))
        tables: dict = {}
        with engine.connect() as connection:
            if engine.dialect.name == "mysql":
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            else:
                connection.exec_driver_sql("BEGIN")
            inspector = inspect(connection)
            for name in sorted(inspector.get_table_names()):
                if name == "alembic_version":
                    continue
                table = Table(name, MetaData(), autoload_with=connection)
                primary_key = list(inspector.get_pk_constraint(name).get("constrained_columns", []))
                if not primary_key:
                    raise MigrationError("源表无主键，停止导出以免产生不稳定身份")
                filename = hashlib.sha256(name.encode()).hexdigest()[:24] + ".jsonl"
                count, redaction_count = 0, 0
                hasher = hashlib.sha256()
                stream = (temporary / filename).open("wb") if temporary else None
                if stream:
                    os.chmod(temporary / filename, 0o600)
                try:
                    statement = select(table).order_by(*(table.c[key] for key in primary_key))
                    for raw in connection.execute(statement).mappings():
                        data, redactions = sanitize(dict(raw))
                        source_id = _row_id(data, primary_key)
                        line = (
                            canonical({"source_id": source_id, "data": data, "redactions": redactions}) + "\n"
                        ).encode()
                        hasher.update(line)
                        if stream:
                            stream.write(line)
                        count += 1
                        redaction_count += len(redactions)
                finally:
                    if stream:
                        stream.close()
                tables[name] = {
                    "file": filename,
                    "count": count,
                    "sha256": hasher.hexdigest(),
                    "primary_key": primary_key,
                    "columns": [column.name for column in table.columns],
                    "foreign_keys": inspector.get_foreign_keys(name),
                    "redactions": redaction_count,
                }
            connection.rollback()
        manifest = {
            "format_version": FORMAT_VERSION,
            "source_commit": source_commit,
            "source_dialect": engine.dialect.name,
            "freeze_attestation": freeze,
            "tables": tables,
            "credential_policy": "secure-reference-only",
        }
        manifest["bundle_id"] = digest(manifest)
        if temporary:
            write_json(temporary / "manifest.json", manifest)
            os.replace(temporary, output)
            temporary = None
        return manifest
    except MigrationError:
        raise
    except Exception as error:
        raise MigrationError("只读导出失败；源库未被工具写入，请在安全终端检查连接和表结构") from error
    finally:
        engine.dispose()
        if temporary:
            shutil.rmtree(temporary)


def load_bundle(bundle: Path) -> tuple[dict, dict[str, list[dict]]]:
    manifest = read_json(bundle / "manifest.json")
    body = {key: value for key, value in manifest.items() if key != "bundle_id"}
    if manifest.get("format_version") != FORMAT_VERSION or digest(body) != manifest.get("bundle_id"):
        raise MigrationError("manifest 格式或内容哈希不匹配")
    validate_freeze(manifest["freeze_attestation"])
    result = {}
    for table, metadata in manifest["tables"].items():
        filename = metadata["file"]
        if Path(filename).name != filename:
            raise MigrationError("manifest 文件路径越界")
        try:
            content = (bundle / filename).read_bytes()
            if hashlib.sha256(content).hexdigest() != metadata["sha256"]:
                raise MigrationError("导出文件内容哈希不匹配")
            rows = [json.loads(line) for line in content.decode().splitlines()]
        except (OSError, ValueError) as error:
            raise MigrationError("导出行文件无法读取") from error
        if len(rows) != metadata["count"]:
            raise MigrationError("导出文件行数与 manifest 不符")
        ids = [row["source_id"] for row in rows]
        if len(set(ids)) != len(ids):
            raise MigrationError("导出包含重复源主键")
        result[table] = rows
    return manifest, result


def _target_id(table: str, source_id: str, namespace: UUID) -> str:
    return str(uuid5(namespace, f"{table}:{source_id}"))


def _seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int(parsed.replace(tzinfo=parsed.tzinfo or UTC).timestamp())
    except ValueError as error:
        raise MigrationError("源时间字段无法按显式 ISO 时间解析") from error


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise MigrationError("映射对象必须使用 1.0 UUID 身份") from error


def _source_references(manifest: dict, rows: dict) -> tuple[list[dict], list[dict]]:
    references, issues = [], []
    for table, metadata in manifest["tables"].items():
        for foreign_key in metadata["foreign_keys"]:
            target_table = foreign_key["referred_table"]
            target_columns = foreign_key["referred_columns"]
            source_columns = foreign_key["constrained_columns"]
            target_keys = {
                canonical([row["data"].get(column) for column in target_columns])
                for row in rows.get(target_table, [])
            }
            for row in rows[table]:
                values = [row["data"].get(column) for column in source_columns]
                if any(value is None for value in values):
                    continue
                reference = {
                    "source_table": table,
                    "source_id": row["source_id"],
                    "columns": source_columns,
                    "target_table": target_table,
                    "target_columns": target_columns,
                    "values": values,
                }
                references.append(reference)
                if canonical(values) not in target_keys:
                    issues.append(reference)
    return references, issues


def build_plan(bundle: Path, mapping: dict) -> dict:
    manifest, rows = load_bundle(bundle)
    if not mapping.get("reviewed_by") or not mapping.get("reviewed_at"):
        raise MigrationError("映射必须记录审核人和审核时间")
    _seconds(mapping["reviewed_at"])
    if mapping.get("format_version") != FORMAT_VERSION:
        raise MigrationError("映射格式版本无效")
    # credential_ref 是安全存储引用；其他输入不得含原始密钥。
    mapping_for_scan = json.loads(canonical(mapping))
    for worker in mapping_for_scan.get("workers", {}).values():
        credential_ref = worker.pop("credential_ref", None)
        if credential_ref and (
            not re.fullmatch(r"(?:vault|secret-ref)://[^\s]+", credential_ref) or sanitize(credential_ref)[1]
        ):
            raise MigrationError("Worker 凭据必须使用无明文秘密的 vault:// 或 secret-ref:// 引用")
    if sanitize(mapping_for_scan)[1]:
        raise MigrationError("映射包含疑似明文凭据")
    namespace = UUID(mapping.get("id_namespace", str(NAMESPACE)))
    actor = mapping.get("migration_actor", {})
    if actor.get("kind") != "SYSTEM":
        raise MigrationError("迁移操作主体必须是显式 SYSTEM 身份")
    actor_id = _uuid(actor.get("id"))
    teams = mapping.get("teams", [])
    employees = mapping.get("employees", [])
    team_ids = {_uuid(team["id"]) for team in teams}
    employee_ids = {_uuid(employee["id"]) for employee in employees}
    team_id = mapping.get("default_team_id")
    if team_id not in team_ids:
        raise MigrationError("必须显式指定迁入的组织 Team")
    for owner in mapping.get("task_owners", {}).values():
        if owner not in employee_ids:
            raise MigrationError("任务主责映射未指向审核过的新员工")
    records = []

    def append(kind: str, identifier: str, data: dict, source: dict | None = None):
        records.append({"kind": kind, "id": identifier, "data": data, "source": source})

    append("actors", actor_id, {**actor, "active": False, "permissions": []})
    for configured_actor in mapping.get("actors", []):
        _uuid(configured_actor["id"])
        if configured_actor.get("kind") not in {"HUMAN", "EMPLOYEE", "SYSTEM"}:
            raise MigrationError("显式 Actor 类型无效")
        append("actors", configured_actor["id"], {**configured_actor, "active": False, "permissions": []})
    for collection in ("teams", "roles", "employees"):
        for item in mapping.get(collection, []):
            _uuid(item["id"])
            # 导入不自动激活人员，也不会在此赋予运行权限。
            data = {**item, "lifecycle": "PENDING_CONFIGURATION"} if collection == "employees" else item
            append(collection, item["id"], data)

    worker_by_employee = {}
    worker_by_environment = {}
    for row in rows.get("opencode_execution_environments", []):
        configured = mapping.get("workers", {}).get(row["source_id"], {})
        identifier = (
            _uuid(configured["id"])
            if configured.get("id")
            else _target_id("workers", row["source_id"], namespace)
        )
        worker_by_environment[row["source_id"]] = identifier
        employee_id = str(row["data"].get("employee_id"))
        if employee_id in worker_by_employee:
            raise MigrationError("旧执行主体存在多个环境，必须先人工对账")
        worker_by_employee[employee_id] = identifier

    sessions_by_task = {}
    for row in rows.get("runtime_sessions", []):
        sessions_by_task.setdefault(str(row["data"].get("task_id")), []).append(row)
    attempts = {}
    for sessions in sessions_by_task.values():
        for index, row in enumerate(
            sorted(sessions, key=lambda item: (item["data"].get("created_at") or "", item["source_id"])),
            start=1,
        ):
            attempts[row["source_id"]] = index

    for table, source_rows in rows.items():
        for row in source_rows:
            old, source_id = row["data"], row["source_id"]
            source = {"table": table, "id": source_id}
            identifier = _target_id(table, source_id, namespace)
            common = {"created_at": _seconds(old.get("created_at")), "revision": 1}
            kind = "historical_archive"
            data = {"read_only": True, "content": old, **common}
            if table == "opencode_execution_environments":
                kind, identifier = "workers", worker_by_environment[source_id]
                configured = mapping.get("workers", {}).get(source_id, {})
                data = {
                    **common,
                    "name": old.get("name"),
                    "host": old.get("host"),
                    "base_url": configured.get("base_url"),
                    "runtime_type": "OPENCODE",
                    "runtime_version": configured.get("runtime_version"),
                    "model": old.get("model_name"),
                    "capability_tags": old.get("labels", []),
                    "workspace_roots": [old["workspace_root"]] if old.get("workspace_root") else [],
                    "credential_ref": configured.get("credential_ref"),
                    "enabled": False,
                    "health": "UNKNOWN",
                    "concurrent_slots": 0,
                    "configuration_state": "PENDING_CONFIGURATION",
                }
            elif table == "digital_employees":
                kind = "historical_execution_subjects"
                data = {
                    **common,
                    "name": old.get("name"),
                    "role_description": old.get("role"),
                    "worker_id": worker_by_employee.get(source_id),
                    "read_only": True,
                    "status": "ARCHIVED",
                    "identity_material": old,
                }
            elif table == "tasks":
                kind = "tasks"
                status = mapping.get("task_status_map", {}).get(old.get("status"))
                if not status:
                    raise MigrationError("任务状态缺少显式映射，禁止猜测新业务终态")
                data = {
                    **common,
                    "team_id": team_id,
                    "created_by_actor": actor_id,
                    "owner_employee_id": mapping.get("task_owners", {}).get(source_id),
                    "title": old.get("title"),
                    "objective": old.get("description", ""),
                    "acceptance_criteria": old.get("acceptance_criteria", []),
                    "status": status,
                    "read_only": True,
                    "completed_at": _seconds(old.get("completed_at")),
                    "continuity_key": "migration:" + identifier,
                }
            elif table == "runtime_sessions":
                kind = "task_executions"
                worker_id = worker_by_employee.get(str(old.get("employee_id")))
                if not worker_id:
                    raise MigrationError("历史 Session 无法映射可信 Worker，须先补齐环境映射")
                data = {
                    **common,
                    "task_id": _target_id("tasks", str(old.get("task_id")), namespace),
                    "worker_id": worker_id,
                    "native_session_id": source_id,
                    "workspace_ref": old.get("workspace"),
                    "attempt_no": attempts[source_id],
                    "native_status": old.get("status"),
                    "read_only": True,
                    "requires_reconciliation": True,
                    "environment": old.get("environment"),
                    "terminal_reason": old.get("terminal_reason"),
                    "finish_reason": old.get("finish_reason"),
                    "started_at": _seconds(old.get("started_at")),
                    "finished_at": _seconds(old.get("finished_at")),
                    "superseded_by": _target_id(table, str(old["superseded_by"]), namespace)
                    if old.get("superseded_by")
                    else None,
                }
            elif table == "knowledge_items":
                kind = "knowledge_items"
                verification = old.get("verification_status") or "UNKNOWN"
                data = {
                    **common,
                    "team_id": team_id,
                    "created_by_actor": actor_id,
                    "title": old.get("title"),
                    "kind": old.get("type", "document"),
                    "content": old.get("content_md", ""),
                    "verification": verification,
                    "status": "ARCHIVED",
                    "read_only": True,
                    "publication_review_required": True,
                    "source_refs": [{"uri": old.get("source_ref")}],
                }
            elif table == "experience_evidence":
                kind = "experience_evidence"
                data = {**common, "content": old, "read_only": True, "verification": "UNKNOWN"}
            elif table == "assistant_conversations":
                kind = "historical_channels"
                data = {
                    **common,
                    "title": old.get("title"),
                    "read_only": True,
                    "visibility": "PRIVATE",
                    "owner_human_id": mapping.get("human_assignments", {}).get(str(old.get("user_id"))),
                    "access_state": "REQUIRES_REVIEW",
                    "native_session_ref": old.get("opencode_session_id"),
                }
            elif table == "assistant_messages":
                kind = "historical_messages"
                data = {
                    **common,
                    "channel_id": _target_id(
                        "assistant_conversations", str(old.get("conversation_id")), namespace
                    ),
                    "content": old.get("content", ""),
                    "read_only": True,
                    "historical_speaker_role": old.get("role"),
                    "sender_kind": "HISTORICAL_SOURCE",
                }
            append(kind, identifier, data, source)

    ids = [(record["kind"], record["id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise MigrationError("显式映射产生重复目标身份")
    references, dangling = _source_references(manifest, rows)
    external_references = []
    for table, source_rows in rows.items():
        for row in source_rows:
            fields = {**EXTERNAL_FIELDS}
            if table == "runtime_sessions":
                fields["id"] = "native_session"
            for field, category in fields.items():
                value = row["data"].get(field)
                if value:
                    external_references.append(
                        {
                            "kind": category,
                            "ref": value,
                            "verification": "UNCHECKED",
                            "source": {"table": table, "id": row["source_id"], "field": field},
                        }
                    )
    plan = {
        "format_version": FORMAT_VERSION,
        "source_bundle_id": manifest["bundle_id"],
        "mapping_sha256": digest(mapping),
        "reviewed_by": mapping["reviewed_by"],
        "reviewed_at": _seconds(mapping["reviewed_at"]),
        "archive_team_id": team_id,
        "migration_actor_id": actor_id,
        "records": records,
        "source_references": references,
        "dangling_references": dangling,
        "external_references": external_references,
        "destination": "PORTABLE_1_0_MAPPING",
        "production_schema_imported": False,
        "cutover_allowed": False,
    }
    plan["plan_id"] = digest(plan)
    return plan


def validate_plan(plan: dict) -> None:
    body = {key: value for key, value in plan.items() if key != "plan_id"}
    if plan.get("format_version") != FORMAT_VERSION or digest(body) != plan.get("plan_id"):
        raise MigrationError("映射产物哈希不匹配")
    if plan.get("destination") != "PORTABLE_1_0_MAPPING":
        raise MigrationError("本适配器只接受审核过的 1.0 portable 映射产物")
    if plan.get("dangling_references"):
        raise MigrationError("源库包含悬空关联，必须先对账后再导入")


def _staging(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    allowed = {"migration_tool_metadata", "migration_batches", "migration_records", "migration_manifest"}
    if tables - allowed or (tables and "migration_tool_metadata" not in tables):
        connection.close()
        raise MigrationError("目标不是专用迁移 staging，拒绝修改业务数据库")
    if tables:
        markers = [row[0] for row in connection.execute("SELECT tool FROM migration_tool_metadata")]
        if markers != ["astra-from-0xx-staging-v1"]:
            connection.close()
            raise MigrationError("目标 staging 标记不匹配，拒绝写入")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS migration_tool_metadata (tool TEXT PRIMARY KEY);
        INSERT OR IGNORE INTO migration_tool_metadata VALUES ('astra-from-0xx-staging-v1');
        CREATE TABLE IF NOT EXISTS migration_batches (
            plan_id TEXT PRIMARY KEY, bundle_id TEXT NOT NULL, state TEXT NOT NULL,
            expected_count INTEGER NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS migration_records (
            kind TEXT NOT NULL, target_id TEXT NOT NULL, plan_id TEXT NOT NULL,
            payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY (kind, target_id)
        );
        CREATE TABLE IF NOT EXISTS migration_manifest (
            plan_id TEXT NOT NULL, source_table TEXT NOT NULL, source_id TEXT NOT NULL,
            target_kind TEXT NOT NULL, target_id TEXT NOT NULL,
            PRIMARY KEY (plan_id, source_table, source_id)
        );
    """)
    connection.commit()
    os.chmod(path, 0o600)
    return connection


def import_staging(plan: dict, path: Path, *, dry_run: bool = False, fail_after: int | None = None) -> dict:
    validate_plan(plan)
    if dry_run:
        return {"dry_run": True, "expected_count": len(plan["records"]), "cutover_allowed": False}
    connection = _staging(path)
    inserted = 0
    try:
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO migration_batches VALUES (?, ?, ?, ?, ?)",
                (plan["plan_id"], plan["source_bundle_id"], "IN_PROGRESS", len(plan["records"]), utcnow()),
            )
            connection.execute(
                "UPDATE migration_batches SET state='IN_PROGRESS',updated_at=? WHERE plan_id=?",
                (utcnow(), plan["plan_id"]),
            )
        for record in plan["records"]:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT plan_id,sha256,payload FROM migration_records WHERE kind=? AND target_id=?",
                    (record["kind"], record["id"]),
                ).fetchone()
                content_hash = digest(record)
                if existing:
                    if (
                        existing["plan_id"] != plan["plan_id"]
                        or existing["sha256"] != content_hash
                        or existing["payload"] != canonical(record)
                    ):
                        raise MigrationError("目标身份已由另一产物占用或内容发生差异；禁止覆盖")
                    continue
                if fail_after is not None and inserted >= fail_after:
                    raise MigrationError("测试注入：导入中断，已提交行可按原产物恢复或显式回滚")
                connection.execute(
                    "INSERT INTO migration_records VALUES (?, ?, ?, ?, ?)",
                    (record["kind"], record["id"], plan["plan_id"], canonical(record), content_hash),
                )
                if record["source"]:
                    connection.execute(
                        "INSERT INTO migration_manifest VALUES (?, ?, ?, ?, ?)",
                        (
                            plan["plan_id"],
                            record["source"]["table"],
                            record["source"]["id"],
                            record["kind"],
                            record["id"],
                        ),
                    )
                inserted += 1
        with connection:
            connection.execute(
                "UPDATE migration_batches SET state='COMPLETE',updated_at=? WHERE plan_id=?",
                (utcnow(), plan["plan_id"]),
            )
        return {
            "plan_id": plan["plan_id"],
            "inserted": inserted,
            "expected_count": len(plan["records"]),
            "state": "COMPLETE",
            "cutover_allowed": False,
        }
    except Exception:
        with connection:
            connection.execute(
                "UPDATE migration_batches SET state='FAILED',updated_at=? WHERE plan_id=?",
                (utcnow(), plan["plan_id"]),
            )
        raise
    finally:
        connection.close()


def rollback_staging(path: Path, plan_id: str) -> dict:
    if not path.is_file():
        raise MigrationError("staging 不存在")
    connection = _staging(path)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute(
                "SELECT count(*) FROM migration_records WHERE plan_id=?", (plan_id,)
            ).fetchone()[0]
            connection.execute("DELETE FROM migration_manifest WHERE plan_id=?", (plan_id,))
            connection.execute("DELETE FROM migration_records WHERE plan_id=?", (plan_id,))
            connection.execute(
                "UPDATE migration_batches SET state='ROLLED_BACK',updated_at=? WHERE plan_id=?",
                (utcnow(), plan_id),
            )
        return {"plan_id": plan_id, "removed": count, "state": "ROLLED_BACK"}
    finally:
        connection.close()


def reconcile(bundle: Path, plan: dict, path: Path) -> dict:
    manifest, source_rows = load_bundle(bundle)
    validate_plan(plan)
    if manifest["bundle_id"] != plan["source_bundle_id"]:
        raise MigrationError("映射产物来自另一导出包")
    if not path.is_file():
        raise MigrationError("staging 不存在")
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        actual = {
            (row["kind"], row["target_id"]): row
            for row in connection.execute(
                "SELECT * FROM migration_records WHERE plan_id=?", (plan["plan_id"],)
            )
        }
        mismatches = []
        for record in plan["records"]:
            stored = actual.get((record["kind"], record["id"]))
            if not stored or stored["sha256"] != digest(record) or stored["payload"] != canonical(record):
                mismatches.append({"kind": record["kind"], "id": record["id"]})
        by_source = Counter()
        expected_sources = {(table, row["source_id"]) for table, rows in source_rows.items() for row in rows}
        actual_sources = set()
        for row in connection.execute("SELECT * FROM migration_manifest WHERE plan_id=?", (plan["plan_id"],)):
            by_source[row["source_table"]] += 1
            actual_sources.add((row["source_table"], row["source_id"]))
        class_counts = {
            table: {
                "exported": metadata["count"],
                "mapped": by_source[table],
                "matched": metadata["count"] == by_source[table],
            }
            for table, metadata in manifest["tables"].items()
        }
        passed = not mismatches and actual_sources == expected_sources and len(actual) == len(plan["records"])
        return {
            "report_version": FORMAT_VERSION,
            "generated_at": utcnow(),
            "plan_id": plan["plan_id"],
            "source_bundle_id": manifest["bundle_id"],
            "source_commit": manifest["source_commit"],
            "class_counts": class_counts,
            "source_identity_match": actual_sources == expected_sources,
            "content_hash_mismatches": mismatches,
            "source_references_checked": len(plan["source_references"]),
            "dangling_references": plan["dangling_references"],
            "external_references": plan["external_references"],
            "credential_redactions": sum(table["redactions"] for table in manifest["tables"].values()),
            "passed_staging": passed,
            "production_schema_imported": False,
            "cutover_allowed": False,
            "unverified": [
                "1.0 正式 schema 导入",
                "真实 Session/Workspace/文件/Skill 可达性与哈希核验",
                "私聊访问授权签收",
                "安全凭据渠道重配置",
                "生产全量验收与正式切换",
            ],
        }
    except sqlite3.DatabaseError as error:
        raise MigrationError("staging 对账失败，请检查目标文件格式") from error
    finally:
        connection.close()
