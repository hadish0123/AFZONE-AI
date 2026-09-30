from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from uuid import UUID

import jwt
import pyotp
from argon2 import PasswordHasher
from cryptography.fernet import Fernet

from app.core.config import get_settings

settings = get_settings()
password_hasher = PasswordHasher()
fernet = Fernet(settings.encryption_key.encode())


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except Exception:
        return False


def create_access_token(user_id: UUID, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise ValueError("invalid token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return sha256(raw.encode()).hexdigest()


def encrypt_secret(value: str) -> str:
    return fernet.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return fernet.decrypt(value.encode()).decode()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, *, username: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name="PRIMEVPN",
    )


def verify_totp(secret: str, code: str) -> bool:
    clean = "".join(ch for ch in code if ch.isdigit())
    return bool(clean) and pyotp.TOTP(secret).verify(clean, valid_window=1)


def generate_recovery_codes(count: int = 8) -> tuple[list[str], list[str]]:
    raw = [secrets.token_hex(4).upper() for _ in range(count)]
    hashed = [sha256(code.encode()).hexdigest() for code in raw]
    return raw, hashed


def recovery_code_hash(code: str) -> str:
    return sha256(code.strip().upper().encode()).hexdigest()
