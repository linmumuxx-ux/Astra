"""把 Worker 指令的发布结果拆成 unpublished、uncertain、published。

已有且 delivery_attempts > 0 的行视为已经发布，避免被当成未发布重新投出。
downgrade 只删除 delivery_state。
"""

import sqlalchemy as sa

from alembic import op

revision = "0041_worker_command_delivery_state"
down_revision = "0040_worker_command_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "worker_commands",
        sa.Column(
            "delivery_state",
            sa.String(length=16),
            nullable=False,
            server_default="unpublished",
        ),
    )
    op.execute("UPDATE worker_commands SET delivery_state = 'published' WHERE delivery_attempts > 0")


def downgrade():
    op.drop_column("worker_commands", "delivery_state")
