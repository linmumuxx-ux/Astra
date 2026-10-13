"""离线 ETL 合约测试：使用隔离 SQLite，不接触真实旧库。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import JSON, Column, ForeignKey, Integer, MetaData, String, Table, Text, create_engine

from migrations.from_0xx.cli import main
from migrations.from_0xx.etl import (
    MigrationError,
    build_plan,
    canonical,
    export_bundle,
    import_staging,
    load_bundle,
    reconcile,
    rollback_staging,
    sanitize,
    write_json,
)

COMMIT = "05dd73142b294a9cb6b2b14a0750b707422aeec3"
ACTOR = "c3ef0da1-c53c-4f0f-82c5-2c6f4e12bc85"
TEAM = "1235896a-942d-44fc-aac9-0074b0e701ec"
EMPLOYEE = "6dc2e2cf-7386-43f6-8189-3395f179e6fe"


@pytest.fixture
def freeze():
    return {
        "frozen_at": "2026-10-13T00:00:00+08:00",
        "confirmed_by": "migration-operator",
        "legacy_writers_stopped": True,
        "backup_ref": "backup://run-001",
        "in_flight_policy": "旧执行已排空；未知副作用由人工对账，不重跑",
    }


@pytest.fixture
def mapping():
    return {
        "format_version": 1,
        "reviewed_by": "migration-reviewer",
        "reviewed_at": "2026-10-13T00:01:00+08:00",
        "migration_actor": {"id": ACTOR, "kind": "SYSTEM", "name": "0.xx 历史迁移"},
        "teams": [{"id": TEAM, "name": "历史归档组织"}],
        "default_team_id": TEAM,
        "task_status_map": {"SUCCEEDED": "COMPLETED", "RUNNING": "NEEDS_RECONCILIATION"},
    }


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    employees = Table(
        "digital_employees",
        metadata,
        Column("id", String, primary_key=True),
        Column("name", String),
        Column("role", String),
    )
    environments = Table(
        "opencode_execution_environments",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("employee_id", ForeignKey("digital_employees.id")),
        Column("name", String),
        Column("host", String),
        Column("workspace_root", String),
        Column("ssh_password", String),
        Column("labels", JSON),
        Column("created_at", String),
    )
    tasks = Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("title", String),
        Column("description", Text),
        Column("acceptance_criteria", JSON),
        Column("status", String),
        Column("employee_id", ForeignKey("digital_employees.id")),
        Column("completed_at", String),
        Column("finished_at", String),
        Column("created_at", String),
    )
    sessions = Table(
        "runtime_sessions",
        metadata,
        Column("id", String, primary_key=True),
        Column("task_id", ForeignKey("tasks.id")),
        Column("employee_id", ForeignKey("digital_employees.id")),
        Column("workspace", String),
        Column("status", String),
        Column("environment", JSON),
        Column("superseded_by", ForeignKey("runtime_sessions.id")),
        Column("created_at", String),
    )
    knowledge = Table(
        "knowledge_items",
        metadata,
        Column("id", String, primary_key=True),
        Column("title", String),
        Column("content_md", Text),
        Column("type", String),
        Column("verification_status", String),
        Column("source_session_id", ForeignKey("runtime_sessions.id")),
        Column("status", String),
        Column("source_path", String),
    )
    evidence = Table(
        "experience_evidence",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("knowledge_id", ForeignKey("knowledge_items.id")),
        Column("file_path", String),
        Column("source_session_id", ForeignKey("runtime_sessions.id")),
        Column("content", Text),
    )
    conversations = Table(
        "assistant_conversations",
        metadata,
        Column("id", String, primary_key=True),
        Column("user_id", String),
        Column("title", String),
        Column("opencode_session_id", String),
    )
    messages = Table(
        "assistant_messages",
        metadata,
        Column("id", String, primary_key=True),
        Column("conversation_id", ForeignKey("assistant_conversations.id")),
        Column("role", String),
        Column("content", Text),
    )
    nodes = Table(
        "gateway_nodes",
        metadata,
        Column("id", String, primary_key=True),
        Column("api_key_encrypted", Text),
        Column("base_url", String),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(employees.insert(), {"id": "old-engineer", "name": "旧执行节点", "role": "研发"})
        connection.execute(
            environments.insert(),
            {
                "id": 7,
                "employee_id": "old-engineer",
                "name": "执行主机",
                "host": "10.0.0.7",
                "workspace_root": "/srv/workspaces",
                "ssh_password": "plaintext-password-never-export",
                "labels": ["python"],
                "created_at": "2026-01-01T00:00:00+00:00",
            },
        )
        connection.execute(
            tasks.insert(),
            [
                {
                    "id": "TASK-19",
                    "title": "历史交付",
                    "description": "保留原始交付目标",
                    "acceptance_criteria": [{"text": "证据须可核验"}],
                    "status": "SUCCEEDED",
                    "employee_id": "old-engineer",
                    "completed_at": "2026-02-01T00:00:00+00:00",
                    "finished_at": "2026-03-01T00:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "TASK-20",
                    "title": "历史运行中",
                    "description": "不得重跑",
                    "acceptance_criteria": [],
                    "status": "RUNNING",
                    "employee_id": "old-engineer",
                    "completed_at": None,
                    "finished_at": "2026-03-01T00:00:00+00:00",
                    "created_at": "2026-01-02T00:00:00+00:00",
                },
            ],
        )
        connection.execute(
            sessions.insert(),
            [
                {
                    "id": "ses_native_1",
                    "task_id": "TASK-19",
                    "employee_id": "old-engineer",
                    "workspace": "/srv/workspaces/task-19",
                    "status": "UNKNOWN",
                    "environment": {
                        "ssh_password": "nested-private",
                        "headers": {"Authorization": "Bearer abc"},
                    },
                    "superseded_by": "ses_native_2",
                    "created_at": "2026-01-01T01:00:00+00:00",
                },
                {
                    "id": "ses_native_2",
                    "task_id": "TASK-19",
                    "employee_id": "old-engineer",
                    "workspace": "/srv/workspaces/task-19-retry",
                    "status": "SUCCEEDED",
                    "environment": {},
                    "superseded_by": None,
                    "created_at": "2026-01-01T02:00:00+00:00",
                },
            ],
        )
        connection.execute(
            knowledge.insert(),
            {
                "id": "KN-1",
                "title": "历史经验",
                "content_md": "保留真实资料",
                "type": "experience",
                "verification_status": None,
                "source_session_id": "ses_native_2",
                "status": "published",
                "source_path": "/srv/wiki/experience.md",
            },
        )
        connection.execute(
            evidence.insert(),
            {
                "id": 3,
                "knowledge_id": "KN-1",
                "file_path": "/srv/artifacts/report.txt",
                "source_session_id": "ses_native_2",
                "content": "历史证据",
            },
        )
        connection.execute(
            conversations.insert(),
            {
                "id": "conv-1",
                "user_id": "human-old",
                "title": "私人历史对话",
                "opencode_session_id": "ses_dm",
            },
        )
        connection.execute(
            messages.insert(),
            {"id": "msg-1", "conversation_id": "conv-1", "role": "assistant", "content": "历史助手发言"},
        )
        connection.execute(
            nodes.insert(),
            {
                "id": "node-1",
                "api_key_encrypted": "encrypted-private-material",
                "base_url": "https://provider.internal/v1",
            },
        )
    engine.dispose()
    return path


def exported(source, tmp_path, freeze):
    bundle = tmp_path / "bundle"
    export_bundle(f"sqlite:///{source}", bundle, freeze, COMMIT)
    return bundle


def test_read_only_export_dry_run_and_no_credentials(source, tmp_path, freeze):
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = export_bundle(f"sqlite:///{source}", tmp_path / "dry", freeze, COMMIT, dry_run=True)
    assert result["tables"]["tasks"]["count"] == 2
    assert not (tmp_path / "dry").exists()
    bundle = exported(source, tmp_path, freeze)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    all_text = "".join(path.read_text() for path in bundle.iterdir())
    secrets = (
        "plaintext-password-never-export",
        "nested-private",
        "Bearer abc",
        "encrypted-private-material",
    )
    for secret in secrets:
        assert secret not in all_text
    manifest, rows = load_bundle(bundle)
    assert manifest["tables"]["runtime_sessions"]["redactions"] == 2
    assert rows["tasks"][0]["data"]["title"] == "历史交付"
    with pytest.raises(MigrationError, match="已存在"):
        export_bundle(f"sqlite:///{source}", bundle, freeze, COMMIT)


def test_freeze_is_required_and_is_not_a_service_stop(source, tmp_path, freeze):
    freeze["legacy_writers_stopped"] = False
    with pytest.raises(MigrationError, match="旧 API"):
        export_bundle(f"sqlite:///{source}", tmp_path / "bad", freeze, COMMIT)
    assert not (tmp_path / "bad").exists()


def test_mapping_has_no_automatic_business_employee_or_runtime_success(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, mapping)
    assert not [record for record in plan["records"] if record["kind"] == "employees"]
    workers = [record for record in plan["records"] if record["kind"] == "workers"]
    assert len(workers) == 1
    assert workers[0]["data"]["enabled"] is False
    assert workers[0]["data"]["health"] == "UNKNOWN"
    tasks = {
        record["source"]["id"]: record["data"] for record in plan["records"] if record["kind"] == "tasks"
    }
    assert tasks["TASK-19"]["owner_employee_id"] is None
    assert tasks["TASK-19"]["read_only"] is True
    assert tasks["TASK-19"]["completed_at"] == 1769904000
    assert tasks["TASK-20"]["completed_at"] is None
    assert tasks["TASK-20"]["status"] == "NEEDS_RECONCILIATION"
    sessions = {
        record["source"]["id"]: record for record in plan["records"] if record["kind"] == "task_executions"
    }
    assert sessions["ses_native_1"]["data"]["native_status"] == "UNKNOWN"
    assert sessions["ses_native_1"]["data"]["superseded_by"] == sessions["ses_native_2"]["id"]
    assert sessions["ses_native_1"]["data"]["worker_id"] == workers[0]["id"]
    assert sessions["ses_native_1"]["data"]["requires_reconciliation"] is True
    knowledge = next(record for record in plan["records"] if record["kind"] == "knowledge_items")
    assert knowledge["data"]["verification"] == "UNKNOWN"
    assert knowledge["data"]["status"] == "ARCHIVED"
    assert plan["cutover_allowed"] is False


def test_explicit_employee_and_human_mapping_preserve_private_archive(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    mapping["employees"] = [{"id": EMPLOYEE, "name": "责任员工"}]
    mapping["task_owners"] = {"TASK-19": EMPLOYEE}
    mapping["human_assignments"] = {"human-old": "human-verified"}
    plan = build_plan(bundle, mapping)
    employee = next(record for record in plan["records"] if record["kind"] == "employees")
    assert employee["data"]["lifecycle"] == "PENDING_CONFIGURATION"
    task = next(
        record
        for record in plan["records"]
        if record["kind"] == "tasks" and record["source"]["id"] == "TASK-19"
    )
    assert task["data"]["owner_employee_id"] == EMPLOYEE
    channel = next(record for record in plan["records"] if record["kind"] == "historical_channels")
    assert channel["data"]["owner_human_id"] == "human-verified"
    assert channel["data"]["visibility"] == "PRIVATE"
    assert channel["data"]["access_state"] == "REQUIRES_REVIEW"
    message = next(record for record in plan["records"] if record["kind"] == "historical_messages")
    assert message["data"]["sender_kind"] == "HISTORICAL_SOURCE"
    assert message["data"]["historical_speaker_role"] == "assistant"


@pytest.mark.parametrize(
    "mutation",
    ["no-review", "guess-state", "unknown-owner", "human-actor", "plaintext"],
)
def test_unsafe_or_ambiguous_mapping_is_rejected(source, tmp_path, freeze, mapping, mutation):
    bundle = exported(source, tmp_path, freeze)
    if mutation == "no-review":
        mapping.pop("reviewed_by")
    elif mutation == "guess-state":
        mapping["task_status_map"] = {}
    elif mutation == "unknown-owner":
        mapping["task_owners"] = {"TASK-19": EMPLOYEE}
    elif mutation == "human-actor":
        mapping["migration_actor"]["kind"] = "HUMAN"
    else:
        mapping["workers"] = {"7": {"ssh_password": "a plaintext secret"}}
    with pytest.raises(MigrationError):
        build_plan(bundle, mapping)


def test_import_failure_resume_idempotence_rollback_and_full_counts(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, mapping)
    target = tmp_path / "staging.sqlite"
    import_staging(plan, target, dry_run=True)
    assert not target.exists()
    with pytest.raises(MigrationError, match="测试注入"):
        import_staging(plan, target, fail_after=4)
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT state FROM migration_batches").fetchone()[0] == "FAILED"
        assert connection.execute("SELECT count(*) FROM migration_records").fetchone()[0] == 4
    resumed = import_staging(plan, target)
    assert resumed["inserted"] == len(plan["records"]) - 4
    assert import_staging(plan, target)["inserted"] == 0
    report = reconcile(bundle, plan, target.resolve())
    assert report["passed_staging"] is True
    assert all(item["matched"] for item in report["class_counts"].values())
    assert report["class_counts"]["gateway_nodes"]["mapped"] == 1
    assert report["source_references_checked"] >= 10
    assert report["external_references"]
    assert report["production_schema_imported"] is False
    assert report["cutover_allowed"] is False
    assert rollback_staging(target, plan["plan_id"])["removed"] == len(plan["records"])
    assert reconcile(bundle, plan, target.resolve())["passed_staging"] is False
    assert import_staging(plan, target)["inserted"] == len(plan["records"])


def test_hash_tampering_and_target_conflict_fail_closed(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, mapping)
    target = tmp_path / "staging.sqlite"
    import_staging(plan, target)
    with sqlite3.connect(target) as connection:
        connection.execute("UPDATE migration_records SET payload='tampered' WHERE kind='tasks'")
    assert reconcile(bundle, plan, target.resolve())["passed_staging"] is False
    with pytest.raises(MigrationError, match="禁止覆盖"):
        import_staging(plan, target)
    altered = json.loads(canonical(plan))
    altered["records"][0]["data"]["name"] = "篡改"
    with pytest.raises(MigrationError, match="哈希"):
        import_staging(altered, target)
    manifest = json.loads((bundle / "manifest.json").read_text())
    row_file = bundle / manifest["tables"]["tasks"]["file"]
    row_file.write_text("{}\n")
    with pytest.raises(MigrationError, match="哈希"):
        load_bundle(bundle)


def test_read_only_source_and_business_target_are_never_created_or_modified(tmp_path, freeze):
    source = tmp_path / "missing.sqlite"
    with pytest.raises(MigrationError, match="不存在"):
        export_bundle(f"sqlite:///{source}", tmp_path / "out", freeze, COMMIT)
    assert not source.exists()


def test_import_refuses_real_database(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    target = tmp_path / "real.sqlite"
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO tasks VALUES ('real-business-task')")
    before = target.read_bytes()
    with pytest.raises(MigrationError, match="拒绝修改"):
        import_staging(build_plan(bundle, mapping), target)
    assert target.read_bytes() == before


def test_dangling_source_references_block_import(source, tmp_path, freeze, mapping):
    with sqlite3.connect(source) as connection:
        connection.execute("UPDATE runtime_sessions SET task_id='missing-task' WHERE id='ses_native_1'")
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, mapping)
    assert plan["dangling_references"]
    with pytest.raises(MigrationError, match="悬空关联"):
        import_staging(plan, tmp_path / "staging.sqlite")


def test_concurrent_same_plan_has_no_duplicate_side_effect(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, mapping)
    target = tmp_path / "staging.sqlite"
    # 先建立专用 staging；线程测试仅验证幂等行事务，不依赖建表竞争。
    try:
        import_staging(plan, target, fail_after=0)
    except MigrationError:
        pass
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: import_staging(plan, target), range(2)))
    assert sum(result["inserted"] for result in results) == len(plan["records"])
    assert reconcile(bundle, plan, target.resolve())["passed_staging"] is True


def test_cli_never_prints_source_url_or_secret(tmp_path, monkeypatch, capsys, freeze):
    freeze_path = tmp_path / "freeze.json"
    write_json(freeze_path, freeze)
    monkeypatch.setenv("ASTRA_0XX_DATABASE_URL", "mysql+missingdriver://user:do-not-print-me@host/db")
    assert (
        main(
            [
                "export",
                "--freeze",
                str(freeze_path),
                "--source-commit",
                COMMIT,
                "--output",
                str(tmp_path / "bundle"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "do-not-print-me" not in captured.err
    assert "mysql+missingdriver" not in captured.err


def test_cli_export_map_dry_run_import_reconcile_and_rollback(
    source,
    tmp_path,
    monkeypatch,
    capsys,
    freeze,
    mapping,
):
    freeze_path, mapping_path = tmp_path / "freeze.json", tmp_path / "mapping.json"
    bundle, plan_path, staging = tmp_path / "cli-bundle", tmp_path / "plan.json", tmp_path / "cli.sqlite"
    report_path = tmp_path / "report.json"
    write_json(freeze_path, freeze)
    write_json(mapping_path, mapping)
    monkeypatch.setenv("ASTRA_0XX_DATABASE_URL", f"sqlite:///{source}")
    assert (
        main(["export", "--freeze", str(freeze_path), "--source-commit", COMMIT, "--output", str(bundle)])
        == 0
    )
    assert (
        main(["map", "--bundle", str(bundle), "--mapping", str(mapping_path), "--output", str(plan_path)])
        == 0
    )
    assert main(["import-staging", "--plan", str(plan_path), "--staging", str(staging), "--dry-run"]) == 0
    assert not staging.exists()
    assert main(["import-staging", "--plan", str(plan_path), "--staging", str(staging)]) == 0
    assert (
        main(
            [
                "reconcile",
                "--bundle",
                str(bundle),
                "--plan",
                str(plan_path),
                "--staging",
                str(staging),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text())
    assert report["passed_staging"] is True
    assert report["cutover_allowed"] is False
    assert main(["rollback-staging", "--plan-id", report["plan_id"], "--staging", str(staging)]) == 0
    assert not capsys.readouterr().err


def test_invalid_freeze_time_and_no_primary_key_are_rejected(source, tmp_path, freeze):
    invalid_freeze = {**freeze, "frozen_at": "REPLACE_WITH_ISO8601_TIME"}
    with pytest.raises(MigrationError, match="时间"):
        export_bundle(f"sqlite:///{source}", tmp_path / "invalid", invalid_freeze, COMMIT)
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unidentified_records (value TEXT)")
    with pytest.raises(MigrationError, match="主键"):
        export_bundle(f"sqlite:///{source}", tmp_path / "no-key", freeze, COMMIT)
    assert not (tmp_path / "no-key").exists()


def test_secure_credential_reference_is_not_a_secret_escape_hatch(source, tmp_path, freeze, mapping):
    bundle = exported(source, tmp_path, freeze)
    mapping["workers"] = {"7": {"credential_ref": "vault://user:cleartext@host/item"}}
    with pytest.raises(MigrationError, match="无明文"):
        build_plan(bundle, mapping)
    mapping["workers"] = {"7": {"credential_ref": "vault://astra/workers/host-7", "runtime_version": "1.4.4"}}
    worker = next(record for record in build_plan(bundle, mapping)["records"] if record["kind"] == "workers")
    assert worker["data"]["credential_ref"] == "vault://astra/workers/host-7"


def test_text_secret_redaction_does_not_remove_token_usage():
    cleaned, redactions = sanitize(
        {
            "content": "访问 https://admin:unsafe-pass@host；Bearer fake-secret；api_key=unsafe-key",
            "total_tokens": 30,
            "input_tokens": 10,
            "token": "hidden",
        }
    )
    assert "unsafe-pass" not in cleaned["content"]
    assert "fake-secret" not in cleaned["content"]
    assert "unsafe-key" not in cleaned["content"]
    assert cleaned["total_tokens"] == 30
    assert cleaned["input_tokens"] == 10
    assert len(redactions) == 2
