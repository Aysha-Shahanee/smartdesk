from typing import Dict, List, Optional, Tuple

from ..config import GITHUB_OWNER, PROJECT_NUMBER
from ..github_client import execute_query


def _build_query(owner_type: str) -> str:
    return '''
    query($owner:String!, $number:Int!, $cursor:String){
      OWNER_TYPE(login:$owner){
        projectV2(number:$number){
          id
          items(first:100, after:$cursor){
            pageInfo{ hasNextPage endCursor }
            nodes{
              id
              type
              content{ ... on Issue{ id } ... on PullRequest{ id } }
              fieldValues(first:50){
                nodes{
                  __typename
                  ... on ProjectV2ItemFieldSingleSelectValue{
                    field{ ... on ProjectV2FieldCommon{ name } }
                    name
                  }
                }
              }
            }
          }
        }
      }
    }
    '''.replace("OWNER_TYPE", owner_type)


def _status_value(field_nodes: List[Dict]) -> Optional[str]:
    for node in field_nodes or []:
        field = node.get("field") or {}
        if field.get("name", "").strip().casefold() == "status":
            return node.get("name")
    return None


def fetch_all_project_items(owner: str = GITHUB_OWNER, number: int = PROJECT_NUMBER,
                            token: Optional[str] = None) -> Tuple[str, List[Dict]]:
    """Return the project node ID and every item using cursor pagination."""
    last_error = None
    for owner_type in ("user", "organization"):
        cursor = None
        results = []
        project_id = None
        while True:
            try:
                data = execute_query(
                    _build_query(owner_type),
                    {"owner": owner, "number": number, "cursor": cursor},
                    token=token,
                )
            except Exception as exc:
                last_error = exc
                text = str(exc)
                if cursor is None and any(fragment in text for fragment in (
                    "FORBIDDEN", "Resource not accessible by personal access token",
                    "Could not resolve to an Organization", "Could not resolve to a User",
                )):
                    break
                raise
            owner_data = data.get(owner_type)
            project = owner_data and owner_data.get("projectV2")
            if not project:
                break
            project_id = project["id"]
            connection = project.get("items") or {}
            for item in connection.get("nodes") or []:
                content = item.get("content") or {}
                results.append({
                    "project_item_id": item.get("id"),
                    "project_id": project_id,
                    "issue_id": content.get("id"),
                    "status": _status_value((item.get("fieldValues") or {}).get("nodes") or []),
                    "type": item.get("type"),
                })
            page_info = connection.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                return project_id, results
            cursor = page_info.get("endCursor")
        if project_id:
            return project_id, results
    if last_error:
        raise last_error
    raise RuntimeError(f"Project {number} is not accessible for owner {owner!r}")


def fetch_current_statuses() -> List[Dict]:
    return fetch_all_project_items()[1]
