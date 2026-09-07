"""Normalize persisted Run waiting state for the final runtime model."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_runtime_final_state"
down_revision = "0015_runtime_orchestrator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BLOCKED was historically used both as an executor result signal and a
    # persisted Run state. The final runtime model persists human waiting only
    # as WAITING_INPUT; executor BLOCKED is translated at the coordinator edge.
    op.execute(
        sa.text(
            "UPDATE runs SET status = 'WAITING_INPUT', executor_status = 'WAITING_INPUT' "
            "WHERE status = 'BLOCKED'"
        )
    )


def downgrade() -> None:
    # The previous representation is ambiguous: WAITING_INPUT rows cannot be
    # distinguished from rows that used to be BLOCKED. Keep the normalized data.
    pass
