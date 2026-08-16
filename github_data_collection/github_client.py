import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import GITHUB_TOKEN, settings

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"


def _create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def execute_query(query, variables=None, timeout: int = 15, token=None):

    access_token = token or GITHUB_TOKEN
    if not access_token:
        settings.validate_github_access()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


    session = _create_session()
    try:
        response = session.post(
            GITHUB_GRAPHQL_URL,
            json={
                "query": query,
                "variables": variables
            },
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise Exception(f"GitHub request failed: {exc}") from exc


    result = response.json()


    if "errors" in result:
        raise Exception(
            result["errors"]
        )


    return result["data"]
