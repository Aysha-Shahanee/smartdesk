import hashlib
import hmac

from app.security import create_registration_token, verify_github_signature, verify_registration_token


def test_github_signature_valid_invalid_and_missing():
    body = b'{"ok":true}'
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, signature, "secret")
    assert not verify_github_signature(body, "sha256=" + "0" * 64, "secret")
    assert not verify_github_signature(body, None, "secret")


def test_registration_token_is_bound_to_installation_and_expiry():
    token = create_registration_token(123, "client-secret", expires_at=200)
    assert verify_registration_token(123, token, "client-secret", now=100)
    assert not verify_registration_token(456, token, "client-secret", now=100)
    assert not verify_registration_token(123, token, "client-secret", now=201)

