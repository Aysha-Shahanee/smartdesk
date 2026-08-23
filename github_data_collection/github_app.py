"""GitHub App installation authentication helpers."""

import time
from urllib.parse import urlencode

import requests


API_URL = "https://api.github.com"


def build_installation_url(app_slug: str, state: str) -> str:
    return f"https://github.com/apps/{app_slug}/installations/new?{urlencode({'state': state})}"


def build_user_authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return "https://github.com/login/oauth/authorize?" + urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    })


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


def exchange_user_code(client_id: str, client_secret: str, code: str,
                       redirect_uri: str, timeout: int = 15) -> str:
    response = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise PermissionError(payload.get("error_description") or "GitHub user authorization failed")
    return token


def get_authenticated_user(user_token: str, timeout: int = 15) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {user_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    transient_statuses = {502, 503, 504}
    for attempt in range(3):
        response = requests.get(
            f"{API_URL}/user", headers=headers, timeout=timeout
        )
        if response.status_code not in transient_statuses or attempt == 2:
            response.raise_for_status()
            return response.json()
        time.sleep(0.25 * (2 ** attempt))
    raise RuntimeError("GitHub user lookup retry loop exited unexpectedly")
