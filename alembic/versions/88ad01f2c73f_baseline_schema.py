"""baseline schema

Revision ID: 88ad01f2c73f
Revises: 45d77bb10cc4
Create Date: 2026-02-28 18:40:35.094074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '88ad01f2c73f'
down_revision: Union[str, Sequence[str], None] = '45d77bb10cc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
