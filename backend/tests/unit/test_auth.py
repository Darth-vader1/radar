from datetime import timedelta
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_password_hash,
    verify_api_key,
    verify_password,
)


def test_password_hashing():
    raw = "MySuperSecurePassword123!"
    hashed = get_password_hash(raw)

    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_tokens():
    user_id = "f47ac10b-58cc-4372-a567-0e02b2c3d479"

    # Access token
    token = create_access_token(subject=user_id, expires_delta=timedelta(minutes=15))
    payload = decode_token(token)

    assert payload.get("sub") == user_id
    assert payload.get("type") == "access"
    assert "exp" in payload

    # Refresh token
    ref_token = create_refresh_token(subject=user_id)
    ref_payload = decode_token(ref_token)

    assert ref_payload.get("sub") == user_id
    assert ref_payload.get("type") == "refresh"


def test_api_key_lifecycle():
    raw_key, prefix, key_hash = generate_api_key()

    assert raw_key.startswith("radar_live_")
    assert prefix == raw_key[:12]
    assert len(key_hash) == 64  # SHA-256 hex length

    assert verify_api_key(raw_key, key_hash) is True
    assert verify_api_key("radar_live_invalidkeywithrandomchars12345", key_hash) is False
