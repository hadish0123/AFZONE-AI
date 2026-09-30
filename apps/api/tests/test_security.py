from app.core.security import (
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    new_totp_secret,
    recovery_code_hash,
    verify_password,
)
import pyotp


def test_password_hash_roundtrip():
    hashed = hash_password("a-secure-password")
    assert hashed != "a-secure-password"
    assert verify_password(hashed, "a-secure-password")
    assert not verify_password(hashed, "wrong-password")


def test_secret_encryption_roundtrip():
    encrypted = encrypt_secret("private-token")
    assert encrypted != "private-token"
    assert decrypt_secret(encrypted) == "private-token"


def test_refresh_token_is_hashed():
    raw, hashed = new_refresh_token()
    assert raw
    assert hashed == hash_refresh_token(raw)
    assert raw != hashed


def test_totp_and_recovery_material():
    secret = new_totp_secret()
    assert pyotp.TOTP(secret).verify(pyotp.TOTP(secret).now())
    raw, hashed = generate_recovery_codes(4)
    assert len(raw) == 4
    assert len(hashed) == 4
    assert recovery_code_hash(raw[0]) == hashed[0]
