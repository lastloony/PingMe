"""add recurrence_anchor to reminders

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reminders', sa.Column('recurrence_anchor', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('reminders', 'recurrence_anchor')