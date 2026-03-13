"""Шифрование текстов напоминаний (Fernet / AES-128-CBC + HMAC-SHA256)"""
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator


def _get_fernet() -> Fernet | None:
    from app.config import settings
    key = settings.reminder_encryption_key
    if not key:
        return None
    return Fernet(key.encode())


def encrypt(text: str) -> str:
    f = _get_fernet()
    if f is None:
        return text
    return f.encrypt(text.encode()).decode()


def decrypt(text: str) -> str:
    f = _get_fernet()
    if f is None:
        return text
    try:
        return f.decrypt(text.encode()).decode()
    except (InvalidToken, Exception):
        # plaintext-fallback для уже существующих незашифрованных записей
        return text


class EncryptedText(TypeDecorator):
    """SQLAlchemy-тип: прозрачно шифрует при записи, расшифровывает при чтении."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return decrypt(value)