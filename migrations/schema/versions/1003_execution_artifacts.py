"""执行产物的不可变 Git 索引和返工续做来源，不复制原生消息。"""

import sqlalchemy as sa
from alembic import op

revision = "1003"
down_revision = "1002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("task_executions") as table:
        table.add_column(sa.Column("artifact_commit", sa.String(64), nullable=True))
        table.add_column(sa.Column("continued_from_execution_id", sa.String(36), nullable=True))
        table.create_foreign_key(
            "fk_execution_continued_from", "task_executions", ["continued_from_execution_id"], ["id"]
        )


def downgrade():
    raise RuntimeError("不删除产物及续做来源；请使用核验过的备份恢复")
