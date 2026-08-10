import requests
from .config import GITHUB_TOKEN


response = requests.get(
    "https://api.github.com/user",
    headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}"
    }
)


print(response.status_code)
print(response.json())
