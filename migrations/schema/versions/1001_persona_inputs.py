"""持久保存 Persona 输入引用与提交意图，保留原生消息事实源。"""

import sqlalchemy as sa
from alembic import op

revision = "1001"
down_revision = "1000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employee_turns", sa.Column("input_refs", sa.JSON(), nullable=True))
    op.add_column("employee_turns", sa.Column("submission_started_at", sa.Integer(), nullable=True))
    op.add_column("employee_turns", sa.Column("budget_reservation", sa.Integer(), nullable=True))
    table = sa.table("employee_turns", sa.column("input_refs", sa.JSON()), sa.column("budget_reservation"))
    op.execute(table.update().values(input_refs={}, budget_reservation=0))
    with op.batch_alter_table("employee_turns") as batch:
        batch.alter_column("input_refs", existing_type=sa.JSON(), nullable=False)
        batch.alter_column("budget_reservation", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("budget_usage") as batch:
        batch.create_unique_constraint(
            "uq_budget_native_purpose", ["actor_id", "purpose", "native_session_id"]
        )


def downgrade():
    raise RuntimeError("不删除履职和预算事实；请使用已核验的备份恢复")
