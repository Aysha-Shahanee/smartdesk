"""GitHub App installation authentication helpers."""

import time
from urllib.parse import urlencode

import requests


API_URL = "https://api.github.com"


def build_installation_url(app_slug: str, state: str) -> str:
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def create_app_jwt(app_id: str, private_key: str) -> str:
    import jwt

    now = int(time.time())
    return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": app_id}, private_key, algorithm="RS256")


def _app_headers(app_jwt: str) -> dict:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {app_jwt}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_installation(app_jwt: str, installation_id: int, timeout: int = 15) -> dict:
    response = requests.get(
        f"{API_URL}/app/installations/{installation_id}",
        headers=_app_headers(app_jwt),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def create_installation_token(app_jwt: str, installation_id: int,
                              timeout: int = 15) -> str:
    response = requests.post(
        f"{API_URL}/app/installations/{installation_id}/access_tokens",
        headers=_app_headers(app_jwt),
        timeout=timeout,
    )
    response.raise_for_status()
    token = response.json().get("token")
    if not token:
        raise RuntimeError("GitHub did not return an installation token")
    return token
