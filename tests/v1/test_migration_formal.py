"""正式 1.0 schema 离线导入测试；全程使用临时 SQLite 与隔离历史文件。"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from domains.database import Base
from domains.governance.models import HistoricalArtifact
from domains.identity.models import Actor
from domains.messaging.models import Channel, ChannelMember, Message
from domains.organization.models import Employee
from domains.runtime.models import Worker, WorkerLease
from domains.work.models import Task, TaskExecution
from migrations.from_0xx.cli import main
from migrations.from_0xx.etl import MigrationError, build_plan, canonical, digest, write_json
from migrations.from_0xx.formal import import_schema, prepare_formal, reconcile_schema
from tests.v1.test_migration_etl import (
    ACTOR,
    EMPLOYEE,
    TEAM,
    exported,
)
from tests.v1.test_migration_etl import (
    freeze as migration_freeze_fixture,
)
from tests.v1.test_migration_etl import (
    mapping as migration_mapping_fixture,
)
from tests.v1.test_migration_etl import (
    source as migration_source_fixture,
)

HUMAN = "8df079e8-0abc-44cd-ae55-8dd5e93b12c3"
ROLE = "4a9bcc34-03ec-458f-bcba-9f940496e804"
freeze = migration_freeze_fixture
mapping = migration_mapping_fixture
source = migration_source_fixture


@pytest.fixture
def formal_mapping(mapping):
    mapping["actors"] = [
        {"id": HUMAN, "name": "历史私聊所有人", "kind": "HUMAN"},
        {"id": EMPLOYEE, "name": "审核的新业务员工候选", "kind": "EMPLOYEE"},
    ]
    mapping["roles"] = [{"id": ROLE, "name": "新工程岗位", "team_id": TEAM, "permissions": ["task.create"]}]
    mapping["employees"] = [
        {
            "id": EMPLOYEE,
            "name": "审核的新业务员工候选",
            "team_id": TEAM,
            "role_id": ROLE,
            "manager_id": HUMAN,
        }
    ]
    mapping["workers"] = {"7": {"base_url": "http://runtime.internal:4096", "runtime_version": "1.4.4"}}
    mapping["task_owners"] = {"TASK-19": EMPLOYEE}
    mapping["human_assignments"] = {"human-old": HUMAN}
    return mapping


@pytest.fixture
def destination(tmp_path):
    path = tmp_path / "v1.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(connection)
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('1003')"))
    engine.dispose()
    return path


def test_real_new_schema_import_keeps_historical_truth_and_archive_hashes(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, formal_mapping)
    target_url = f"sqlite:///{destination}"
    ledger, artifact_root = tmp_path / "formal-ledger.sqlite", tmp_path / "artifacts"
    dry_run = import_schema(bundle, plan, target_url, ledger, artifact_root, dry_run=True)
    assert dry_run["expected_target_rows"] > len(plan["records"])
    assert not ledger.exists()
    assert not artifact_root.exists()
    result = import_schema(bundle, plan, target_url, ledger, artifact_root)
    assert result["formal_schema_imported"] is True
    assert result["cutover_allowed"] is False
    assert result["source_rows_archived"] == sum(record["source"] is not None for record in plan["records"])
    engine = create_engine(target_url)
    with engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(WorkerLease)).scalar_one() == 0
        worker = connection.execute(select(Worker)).mappings().one()
        assert worker["enabled"] is False
        assert worker["base_url"] == "http://runtime.internal:4096"
        employee = connection.execute(select(Employee)).mappings().one()
        assert employee["lifecycle"] == "PAUSED"
        assert employee["permissions"] == []
        assert all(row["active"] is False for row in connection.execute(select(Actor)).mappings())
        tasks = connection.execute(select(Task).order_by(Task.title)).mappings().all()
        completed = next(task for task in tasks if task["title"] == "历史交付")
        running = next(task for task in tasks if task["title"] == "历史运行中")
        assert completed["owner_employee_id"] == EMPLOYEE
        assert completed["completed_at"] == 1769904000
        assert completed["created_by_actor"] == ACTOR
        assert running["owner_employee_id"] is None
        assert running["completed_at"] is None
        assert all(task["read_only"] for task in tasks)
        executions = connection.execute(select(TaskExecution)).mappings().all()
        assert all(row["lease_id"] is None and row["lease_fence"] is None for row in executions)
        assert all(row["read_only"] and row["state"] == "HISTORICAL" for row in executions)
        unknown = next(row for row in executions if row["native_session_id"] == "ses_native_1")
        assert unknown["evidence_refs"][0]["native_status"] == "UNKNOWN"
        channel = connection.execute(select(Channel)).mappings().one()
        assert channel["read_only"] is True
        assert channel["kind"] == "ARCHIVE"
        member = connection.execute(select(ChannelMember)).mappings().one()
        assert member["actor_id"] == HUMAN
        message = connection.execute(select(Message)).mappings().one()
        assert message["sender_id"] == ACTOR
        assert message["provenance"]["historical_speaker_role"] == "assistant"
        assert "old" not in canonical(message["provenance"])
        artifacts = connection.execute(select(HistoricalArtifact)).mappings().all()
        assert len(artifacts) == result["source_rows_archived"]
        private = [item for item in artifacts if item["visibility"] == "PRIVATE"]
        assert len(private) == 2
        assert all(item["owner_actor_id"] == HUMAN for item in private)
        for item in artifacts:
            path = artifact_root / item["content_ref"].removeprefix("artifact://")
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        assert "migration_manifest" not in Base.metadata.tables
    engine.dispose()
    again = import_schema(bundle, plan, target_url, ledger, artifact_root)
    assert again["inserted"] == 0 and again["recovered"] is True
    before = destination.read_bytes(), ledger.read_bytes()
    report = reconcile_schema(bundle, plan, target_url, ledger, artifact_root)
    assert report["passed_formal_reconciliation"] is True
    assert report["source_archive_counts"]["tasks"] == 2
    assert before == (destination.read_bytes(), ledger.read_bytes())
    if destination_path := os.getenv("ASTRA_V1_MIGRATION_TEST_REPORT"):
        path = Path(destination_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "kind": "isolated_fixture_formal_schema_reconciliation",
                    "schema_revision": "1003",
                    "whole_system_acceptance": False,
                    "production_source_accessed": False,
                    "cutover_allowed": False,
                    "source_description": "测试夹具创建的只读旧模型 SQLite，不是生产旧库",
                    "result": report,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )


def test_formal_failure_rolls_back_every_domain_row_and_rerun_recovers(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, formal_mapping)
    target_url = f"sqlite:///{destination}"
    ledger, artifacts = tmp_path / "ledger.sqlite", tmp_path / "artifacts"
    with pytest.raises(MigrationError, match="整个目标事务回滚"):
        import_schema(bundle, plan, target_url, ledger, artifacts, fail_after=7)
    with sqlite3.connect(destination) as connection:
        for table in Base.metadata.tables:
            assert connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0
    recovered = import_schema(bundle, plan, target_url, ledger, artifacts)
    assert recovered["inserted"] > 7


def test_target_commit_then_ledger_crash_is_reconciled_without_double_insert(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, formal_mapping)
    target_url = f"sqlite:///{destination}"
    ledger, artifacts = tmp_path / "ledger.sqlite", tmp_path / "artifacts"
    with pytest.raises(MigrationError, match="目标已提交"):
        import_schema(bundle, plan, target_url, ledger, artifacts, fail_after_commit=True)
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 2
    recovered = import_schema(bundle, plan, target_url, ledger, artifacts)
    assert recovered["inserted"] == 0
    assert recovered["recovered"] is True


def test_changed_domain_fact_or_archive_content_blocks_reimport(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, formal_mapping)
    target_url = f"sqlite:///{destination}"
    ledger, artifacts = tmp_path / "ledger.sqlite", tmp_path / "artifacts"
    import_schema(bundle, plan, target_url, ledger, artifacts)
    with sqlite3.connect(destination) as connection:
        connection.execute("UPDATE tasks SET objective='修改后的新事实'")
    assert (
        reconcile_schema(bundle, plan, target_url, ledger, artifacts)["passed_formal_reconciliation"] is False
    )
    with pytest.raises(MigrationError, match="拒绝部分覆盖"):
        import_schema(bundle, plan, target_url, ledger, artifacts)
    first = next(artifacts.glob("*.json"))
    first.write_text("tampered")
    with pytest.raises(MigrationError, match="归档文件"):
        import_schema(bundle, plan, target_url, ledger, artifacts)


def test_old_database_and_uninitialized_schema_are_rejected_without_writes(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
):
    bundle = exported(source, tmp_path, freeze)
    plan = build_plan(bundle, formal_mapping)
    before = source.read_bytes()
    with pytest.raises(MigrationError, match="拒绝修改旧库"):
        import_schema(bundle, plan, f"sqlite:///{source}", tmp_path / "ledger.sqlite", tmp_path / "artifacts")
    assert source.read_bytes() == before
    assert not (tmp_path / "ledger.sqlite").exists()
    with sqlite3.connect(destination) as connection:
        connection.execute("UPDATE alembic_version SET version_num='9999'")
    with pytest.raises(MigrationError, match="revision"):
        import_schema(
            bundle, plan, f"sqlite:///{destination}", tmp_path / "ledger.sqlite", tmp_path / "artifacts"
        )


def test_missing_explicit_worker_endpoint_or_unknown_target_kind_cannot_be_skipped(
    source,
    tmp_path,
    freeze,
    formal_mapping,
):
    bundle = exported(source, tmp_path, freeze)
    formal_mapping["workers"] = {}
    with pytest.raises(MigrationError, match="base_url"):
        prepare_formal(bundle, build_plan(bundle, formal_mapping))
    formal_mapping["workers"] = {"7": {"base_url": "http://runtime.internal:4096"}}
    plan = build_plan(bundle, formal_mapping)
    plan["records"][0]["kind"] = "unknown-domain"
    plan["plan_id"] = digest({key: value for key, value in plan.items() if key != "plan_id"})
    with pytest.raises(MigrationError, match="未支持"):
        prepare_formal(bundle, plan)


def test_formal_cli_reports_real_schema_import_without_claiming_cutover(
    source,
    tmp_path,
    freeze,
    formal_mapping,
    destination,
    monkeypatch,
    capsys,
):
    bundle = exported(source, tmp_path, freeze)
    plan_path, report_path = tmp_path / "plan.json", tmp_path / "report.json"
    write_json(plan_path, build_plan(bundle, formal_mapping))
    monkeypatch.setenv("ASTRA_1_0_MIGRATION_TARGET_URL", f"sqlite:///{destination}")
    assert (
        main(
            [
                "import-schema",
                "--bundle",
                str(bundle),
                "--plan",
                str(plan_path),
                "--ledger",
                str(tmp_path / "ledger.sqlite"),
                "--artifact-root",
                str(tmp_path / "artifacts"),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text())
    assert report["formal_schema_imported"] is True
    assert report["cutover_allowed"] is False
    assert report["archive_only_source_tables"]
    assert not capsys.readouterr().err
