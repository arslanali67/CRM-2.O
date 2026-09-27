"""Owner password hashing (stdlib scrypt).

Hash format: scrypt:<salt_hex>:<hash_hex>. Uses ':' not '$' because
Docker Compose would interpolate '$' in .env values.

Run `python -m app.auth` to generate a hash for OWNER_PASSWORD_HASH.
"""
import getpass
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt:{salt.hex()}:{_derive(password, salt).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split(":")
        if scheme != "scrypt":
            return False
        return hmac.compare_digest(_derive(password, bytes.fromhex(salt_hex)).hex(), hash_hex)
    except ValueError:
        return False


if __name__ == "__main__":
    pw = getpass.getpass("Owner password: ")
    if len(pw) < 12:
        raise SystemExit("Use at least 12 characters.")
    if pw != getpass.getpass("Repeat: "):
        raise SystemExit("Passwords do not match.")
    print(hash_password(pw))
