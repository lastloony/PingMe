"""
Тесты модуля app/crypto.py.

Запуск:
    pytest tests/test_crypto.py -v
"""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.crypto import encrypt, decrypt, EncryptedText


TEST_KEY = Fernet.generate_key().decode()


def _with_key(key: str = TEST_KEY):
    return patch("app.crypto._get_fernet", return_value=Fernet(key.encode()))


def _without_key():
    return patch("app.crypto._get_fernet", return_value=None)


# ---------------------------------------------------------------------------
# encrypt / decrypt — с ключом
# ---------------------------------------------------------------------------

def test_encrypt_returns_different_string():
    with _with_key():
        assert encrypt("купить молоко") != "купить молоко"


def test_encrypt_decrypt_roundtrip():
    with _with_key():
        assert decrypt(encrypt("позвонить маме")) == "позвонить маме"


def test_encrypt_produces_valid_fernet_token():
    with _with_key():
        token = encrypt("тест")
    # Fernet-токены начинаются с 'gAAA'
    assert token.startswith("gAAA")


def test_decrypt_plaintext_fallback():
    """decrypt на незашифрованной строке возвращает её как есть."""
    with _with_key():
        assert decrypt("обычный текст") == "обычный текст"


def test_decrypt_empty_string():
    with _with_key():
        assert decrypt("") == ""


# ---------------------------------------------------------------------------
# encrypt / decrypt — без ключа
# ---------------------------------------------------------------------------

def test_encrypt_without_key_returns_original():
    with _without_key():
        assert encrypt("текст") == "текст"


def test_decrypt_without_key_returns_original():
    with _without_key():
        assert decrypt("текст") == "текст"


# ---------------------------------------------------------------------------
# EncryptedText TypeDecorator
# ---------------------------------------------------------------------------

@pytest.fixture
def col():
    return EncryptedText()


def test_bind_param_encrypts(col):
    with _with_key():
        result = col.process_bind_param("встреча в пятницу", dialect=None)
    assert result != "встреча в пятницу"
    assert result.startswith("gAAA")


def test_bind_param_none(col):
    with _with_key():
        assert col.process_bind_param(None, dialect=None) is None


def test_result_value_decrypts(col):
    with _with_key():
        token = encrypt("выпить таблетку")
        assert col.process_result_value(token, dialect=None) == "выпить таблетку"


def test_result_value_none(col):
    with _with_key():
        assert col.process_result_value(None, dialect=None) is None


def test_result_value_plaintext_fallback(col):
    """Старые незашифрованные записи читаются без ошибок."""
    with _with_key():
        assert col.process_result_value("старый текст", dialect=None) == "старый текст"


def test_bind_and_result_roundtrip(col):
    with _with_key():
        encrypted = col.process_bind_param("напомни про встречу", dialect=None)
        decrypted = col.process_result_value(encrypted, dialect=None)
    assert decrypted == "напомни про встречу"