"""backfill recurrence_anchor for existing recurring reminders

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-02-26 00:00:00.000000

Для всех периодических напоминаний (recurrence IS NOT NULL), у которых
recurrence_anchor не был установлен (NULL), проставляем anchor = remind_at.
Это корректирует старые записи, созданные до появления поля recurrence_anchor.
"""
from alembic import op

revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE reminders
        SET recurrence_anchor = remind_at
        WHERE recurrence IS NOT NULL
          AND recurrence_anchor IS NULL
    """)


def downgrade():
    # Откат невозможен однозначно: не знаем, какие anchor были NULL изначально.
    # Оставляем данные как есть.
    pass