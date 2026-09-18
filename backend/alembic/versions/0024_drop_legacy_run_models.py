"""Drop legacy Run execution models and mirrors.

Phase 4: OpenCode Session is the execution fact source and RuntimeSession is its
index. The Run/ToolUsage/Evidence/TaskSession/SessionMessage/RunInquiry tables
and remaining run references are no longer produced or read.

This migration is intentionally irreversible.
"""

from alembic import op
import sqlalchemy as sa

revision = "0024_drop_legacy_run_models"
down_revision = "0023_runtime_session_usage"
branch_labels = None
depends_on = None


def upgrade():
    # SQLite batch mode recreates the table and would try to rebuild an index on
    # the dropped column, so each run index is removed first.
    op.drop_index("ix_knowledge_items_source_run_id", table_name="knowledge_items")
    op.drop_index("ix_experience_evidence_run_id", table_name="experience_evidence")
    op.drop_index("ix_knowledge_usage_run_id", table_name="knowledge_usage")

    with op.batch_alter_table("events") as batch:
        batch.drop_column("run_id")

    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_column("source_run_id")

    with op.batch_alter_table("experience_evidence") as batch:
        batch.drop_column("run_id")

    with op.batch_alter_table("knowledge_usage") as batch:
        batch.drop_column("run_id")

    for table in (
        "session_messages",
        "run_inquiries",
        "task_sessions",
        "tool_usages",
        "evidence",
        "runs",
    ):
        op.drop_table(table)


def downgrade():
    raise RuntimeError("Legacy Run models are removed permanently; restore a backup")