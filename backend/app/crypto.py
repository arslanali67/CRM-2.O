"""Credential encryption at rest (M11, pulled forward from M30).

The key comes only from the CREDENTIALS_KEY environment variable (.env); it is never stored
in the database. Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from cryptography.fernet import Fernet, InvalidToken

from app import settings


class CredentialsKeyError(RuntimeError):
    pass


def _fernet() -> Fernet:
    try:
        return Fernet(settings.CREDENTIALS_KEY)
    except (ValueError, TypeError):
        raise CredentialsKeyError("CREDENTIALS_KEY is missing or invalid; set it in .env") from None


def encrypt(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt(token: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(token)).decode()
    except InvalidToken:
        raise CredentialsKeyError("stored credentials cannot be decrypted with this CREDENTIALS_KEY; "
                                  "re-enter the app password") from None
