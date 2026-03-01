"""tal-m1-001 run lifecycle

Revision ID: b44dfdc3dd0b
Revises: 88ad01f2c73f
Create Date: 2026-02-28 19:05:02.118430

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b44dfdc3dd0b'
down_revision: Union[str, Sequence[str], None] = '88ad01f2c73f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALLOWED = ("IDLE","SCANNING","HOLDING_READY","PLANNED","EXECUTING","COMPLETE","FAILED")


def upgrade():
    allowed_list = ",".join([f"'{s}'" for s in ALLOWED])

    # Normalize bad/unknown statuses to IDLE
    op.execute(f"""
        UPDATE runs
        SET status = 'IDLE'
        WHERE status IS NULL OR status NOT IN ({allowed_list});
    """)

    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("failed_code", sa.Text(), nullable=True))
        batch.add_column(sa.Column("failed_message", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_runs_status_allowed",
            f"status IN ({allowed_list})"
        )


def downgrade():
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("ck_runs_status_allowed", type_="check")
        batch.drop_column("failed_message")
        batch.drop_column("failed_code")