"""记录 Worker 指令的投递次数、最近投递时间和投递 epoch。

已有指令按尚未投递处理。downgrade 只删除这三列。
"""

import sqlalchemy as sa

from alembic import op

revision = "0040_worker_command_delivery"
down_revision = "0039_worker_gateway"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "worker_commands",
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("worker_commands", sa.Column("last_dispatched_at", sa.DateTime(), nullable=True))
    op.add_column("worker_commands", sa.Column("dispatched_epoch", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("worker_commands", "dispatched_epoch")
    op.drop_column("worker_commands", "last_dispatched_at")
    op.drop_column("worker_commands", "delivery_attempts")
