"""add recurrence to reminders

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-02-24 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('reminders', sa.Column('recurrence', sa.String(20), nullable=True))


def downgrade():
    op.drop_column('reminders', 'recurrence')
