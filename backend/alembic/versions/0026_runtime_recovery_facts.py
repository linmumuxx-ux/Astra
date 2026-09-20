"""Persist task Git baseline and idempotent terminal artifact progress."""

from alembic import op
import sqlalchemy as sa

revision = "0026_runtime_recovery_facts"
down_revision = "0025_drop_task_result"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runtime_sessions") as batch:
        batch.add_column(sa.Column("workspace_base_commit", sa.String(64), nullable=True))
    with op.batch_alter_table("task_summaries") as batch:
        batch.add_column(
            sa.Column(
                "artifacts_processed_generation",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("task_summaries") as batch:
        batch.drop_column("artifacts_processed_generation")
    with op.batch_alter_table("runtime_sessions") as batch:
        batch.drop_column("workspace_base_commit")
