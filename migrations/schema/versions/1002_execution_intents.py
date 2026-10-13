"""执行只保存工作区基线与提交/停止意图，原生消息仍为执行事实源。"""

import sqlalchemy as sa
from alembic import op

revision = "1002"
down_revision = "1001"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("workspace_base_commit", sa.String(64)),
        ("preparation_started_at", sa.Integer()),
        ("submission_started_at", sa.Integer()),
        ("permission_digest", sa.String(64)),
        ("stop_requested", sa.String(16)),
        ("abort_started_at", sa.Integer()),
    ]:
        op.add_column("task_executions", sa.Column(name, kind, nullable=True))


def downgrade():
    raise RuntimeError("不删除执行提交与停止事实；请使用已核验备份恢复")
