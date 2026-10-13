import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parents[2]


def migrate(path):
    env = {**os.environ, "ASTRA_V1_DATABASE_URL": f"sqlite+aiosqlite:///{path}"}
    return subprocess.run(
        [sys.executable, "-m", "apps.api.manage", "migrate"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_frozen_initial_schema_matches_new_models_and_repeats(tmp_path):
    from domains.database import Base

    path = tmp_path / "new.db"
    first = migrate(path)
    assert first.returncode == 0, first.stderr
    with create_engine(f"sqlite:///{path}").connect() as connection:
        actual = inspect(connection)
        assert set(actual.get_table_names()) == set(Base.metadata.tables) | {"alembic_version"}
        for name, table in Base.metadata.tables.items():
            assert {c["name"] for c in actual.get_columns(name)} == set(table.columns.keys())
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "1003"
    assert migrate(path).returncode == 0


def test_initial_schema_refuses_existing_business_database(tmp_path):
    path = tmp_path / "old.db"
    with create_engine(f"sqlite:///{path}").begin() as connection:
        connection.execute(text("CREATE TABLE digital_employees (id TEXT PRIMARY KEY)"))
        connection.execute(text("INSERT INTO digital_employees VALUES ('preserve')"))
    result = migrate(path)
    assert result.returncode != 0
    with create_engine(f"sqlite:///{path}").connect() as connection:
        assert connection.execute(text("SELECT id FROM digital_employees")).scalar() == "preserve"
        assert "actors" not in inspect(connection).get_table_names()


def test_runtime_has_no_old_business_or_migration_imports():
    import ast

    violations = []
    for directory in [ROOT / "apps/api", ROOT / "apps/services", ROOT / "agents", ROOT / "domains"]:
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(
                    name == "app" or name.startswith(("app.", "backend.", "migrations.")) for name in names
                ):
                    violations.append(str(path.relative_to(ROOT)))
    assert violations == []
