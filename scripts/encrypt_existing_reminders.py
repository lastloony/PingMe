"""
Миграция: шифрует тексты существующих напоминаний в БД.

Запускать ОДИН РАЗ после добавления REMINDER_ENCRYPTION_KEY в .env:
    python scripts/encrypt_existing_reminders.py

Скрипт пропускает уже зашифрованные записи (безопасно запускать повторно).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text as sa_text
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.database.base import AsyncSessionLocal


def _is_encrypted(value: str, f: Fernet) -> bool:
    """Проверяет, зашифрована ли строка этим ключом."""
    try:
        f.decrypt(value.encode())
        return True
    except (InvalidToken, Exception):
        return False


async def main():
    if not settings.reminder_encryption_key:
        print("❌ REMINDER_ENCRYPTION_KEY не задан в .env — нечего делать.")
        sys.exit(1)

    f = Fernet(settings.reminder_encryption_key.encode())

    async with AsyncSessionLocal() as session:
        result = await session.execute(sa_text("SELECT id, text FROM reminders"))
        rows = result.fetchall()

        if not rows:
            print("ℹ️  Таблица reminders пуста.")
            return

        updated = 0
        skipped = 0

        for row_id, raw_text in rows:
            if _is_encrypted(raw_text, f):
                skipped += 1
                continue

            encrypted = f.encrypt(raw_text.encode()).decode()
            await session.execute(
                sa_text("UPDATE reminders SET text = :text WHERE id = :id"),
                {"text": encrypted, "id": row_id},
            )
            updated += 1

        await session.commit()

    print(f"✅ Готово: зашифровано {updated}, пропущено (уже зашифровано) {skipped}.")


if __name__ == "__main__":
    asyncio.run(main())