"""add is_confirmed and message_id to reminders

Revision ID: c3c0391c7513
Revises:
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3c0391c7513'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('reminders', sa.Column('is_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('reminders', sa.Column('message_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('reminders', 'message_id')
    op.drop_column('reminders', 'is_confirmed')
