import hashlib
import hmac
import time


def verify_github_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not secret or not signature or not signature.startswith("sha256="):
        return False
    supplied = signature.removeprefix("sha256=")
    if len(supplied) != 64:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def create_registration_token(
    installation_id: int, secret: str, *, expires_at: int
) -> str:
    message = f"v1:{installation_id}:{expires_at}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"v1.{expires_at}.{digest}"


def verify_registration_token(
    installation_id: int, token: str, secret: str, *, now: int | None = None
) -> bool:
    if not secret:
        return False
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1" or len(parts[2]) != 64:
        return False
    try:
        expires_at = int(parts[1])
    except ValueError:
        return False
    current_time = int(time.time()) if now is None else now
    if expires_at < current_time:
        return False
    expected = create_registration_token(
        installation_id, secret, expires_at=expires_at
    )
    return hmac.compare_digest(token, expected)

