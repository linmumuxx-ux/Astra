"""Task summary and session-anchored experience provenance.

Phase 1B: one TaskSummary per Task, and experience idempotency/verification
anchored on the producing RuntimeSession. Run/Evidence legacy tables are not
touched.
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_task_summary_experience"
down_revision = "0021_runtime_session_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_summaries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_session_id", sa.String(160), nullable=True),
        sa.Column("referenced_session_ids", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("acceptance_results", sa.JSON(), nullable=False),
        sa.Column("key_changes", sa.JSON(), nullable=False),
        sa.Column("source_status", sa.String(32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("generated_by", sa.String(120), nullable=False),
        sa.Column("source_ref_snapshot", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["primary_session_id"],
            ["runtime_sessions.id"],
            name="fk_task_summaries_primary_session_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_task_summaries_task_id", "task_summaries", ["task_id"], unique=True)
    op.create_index("ix_task_summaries_stale", "task_summaries", ["stale"])

    with op.batch_alter_table("knowledge_items") as batch:
        batch.add_column(sa.Column("origin", sa.String(32), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("dedupe_key", sa.String(200), nullable=True))
        batch.add_column(sa.Column("fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("experience_type", sa.String(64), nullable=True))
        batch.add_column(sa.Column("scope", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("session_status_at_submission", sa.String(32), nullable=True))
        batch.add_column(sa.Column("verification_session_status", sa.String(32), nullable=True))
        batch.add_column(sa.Column("verification_message_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("session_last_message_id_at_verification", sa.String(160), nullable=True))
        batch.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("source_ref_snapshot", sa.JSON(), nullable=True))
        batch.create_index("ix_knowledge_items_dedupe_key", ["dedupe_key"])
        batch.create_unique_constraint(
            "uq_knowledge_dedupe", ["dedupe_key", "fingerprint"]
        )

    with op.batch_alter_table("experience_evidence") as batch:
        batch.add_column(sa.Column("source_session_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("message_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("part_id", sa.String(160), nullable=True))
        batch.add_column(sa.Column("file_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("diff_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_experience_evidence_source_session_id", ["source_session_id"])
        batch.create_foreign_key(
            "fk_experience_evidence_source_session_id",
            "runtime_sessions",
            ["source_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("knowledge_usage") as batch:
        batch.add_column(sa.Column("session_id", sa.String(160), nullable=True))
        batch.create_index("ix_knowledge_usage_session_id", ["session_id"])
        batch.create_foreign_key(
            "fk_knowledge_usage_session_id",
            "runtime_sessions",
            ["session_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("knowledge_usage") as batch:
        batch.drop_constraint("fk_knowledge_usage_session_id", type_="foreignkey")
        batch.drop_index("ix_knowledge_usage_session_id")
        batch.drop_column("session_id")

    with op.batch_alter_table("experience_evidence") as batch:
        batch.drop_constraint("fk_experience_evidence_source_session_id", type_="foreignkey")
        batch.drop_index("ix_experience_evidence_source_session_id")
        for column in ("captured_at", "diff_hash", "file_path", "part_id", "message_id", "source_session_id"):
            batch.drop_column(column)

    with op.batch_alter_table("knowledge_items") as batch:
        batch.drop_constraint("uq_knowledge_dedupe", type_="unique")
        batch.drop_index("ix_knowledge_items_dedupe_key")
        for column in (
            "source_ref_snapshot",
            "verified_at",
            "session_last_message_id_at_verification",
            "verification_message_id",
            "verification_session_status",
            "session_status_at_submission",
            "scope",
            "experience_type",
            "fingerprint",
            "dedupe_key",
            "origin",
        ):
            batch.drop_column(column)

    op.drop_index("ix_task_summaries_stale", table_name="task_summaries")
    op.drop_index("ix_task_summaries_task_id", table_name="task_summaries")
    op.drop_table("task_summaries")