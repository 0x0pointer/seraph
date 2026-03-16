"""Unit tests for app/core/security.py — hash, verify, JWT encode/decode."""
import pytest
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        assert hash_password("mysecret") != "mysecret"

    def test_hash_starts_with_bcrypt_prefix(self):
        assert hash_password("mysecret").startswith("$2b$")

    def test_same_password_produces_different_hashes(self):
        # bcrypt uses random salt
        assert hash_password("same") != hash_password("same")

    def test_verify_correct_password(self):
        hashed = hash_password("correct_password_123!")
        assert verify_password("correct_password_123!", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct_password_123!")
        assert verify_password("wrong_password_456!", hashed) is False

    def test_verify_empty_string_fails(self):
        hashed = hash_password("correct_password_123!")
        assert verify_password("", hashed) is False


class TestJWTTokens:
    def test_create_token_returns_string(self):
        token = create_access_token({"sub": "alice", "role": "viewer"})
        assert isinstance(token, str)
        assert len(token) > 20

    def test_decode_valid_token(self):
        token = create_access_token({"sub": "alice", "role": "viewer"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "alice"
        assert payload["role"] == "viewer"

    def test_decoded_payload_contains_exp(self):
        token = create_access_token({"sub": "alice"})
        payload = decode_access_token(token)
        assert "exp" in payload

    def test_decode_invalid_token_returns_none(self):
        assert decode_access_token("not.a.valid.token") is None

    def test_decode_tampered_token_returns_none(self):
        token = create_access_token({"sub": "alice"})
        tampered = token[:-5] + "XXXXX"
        assert decode_access_token(tampered) is None

    def test_decode_empty_string_returns_none(self):
        assert decode_access_token("") is None

    def test_extra_claims_are_preserved(self):
        token = create_access_token({"sub": "bob", "org_id": 42, "impersonated_by": "admin"})
        payload = decode_access_token(token)
        assert payload["org_id"] == 42
        assert payload["impersonated_by"] == "admin"
