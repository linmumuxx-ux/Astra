"""RuntimeSession aggregate usage for Dashboard/Usage on the Session fact source."""

from alembic import op
import sqlalchemy as sa

revision = "0023_runtime_session_usage"
down_revision = "0022_task_summary_experience"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runtime_sessions") as batch:
        batch.add_column(sa.Column("input_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("output_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cache_read_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cache_write_tokens", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("llm_call_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("tool_usage", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("runtime_sessions") as batch:
        for column in (
            "tool_usage",
            "llm_call_count",
            "cache_write_tokens",
            "cache_read_tokens",
            "output_tokens",
            "input_tokens",
        ):
            batch.drop_column(column)