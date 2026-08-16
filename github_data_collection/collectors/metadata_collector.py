from typing import Dict, Optional, List
from datetime import datetime, timezone
from ..github_client import execute_query


class UnsupportedProjectItemError(ValueError):
    """The selected ProjectV2 item is not backed by a GitHub Issue."""


def _build_query_for_item():
    return '''
    query($id:ID!){
      node(id:$id){
        ... on ProjectV2Item{
          id
          content{
            __typename
            ... on Issue{
              id
              number
              title
              body
              state
              createdAt
              updatedAt
              repository{ nameWithOwner }
              comments{
                totalCount
              }
              labels(first:50){
                nodes{ name }
              }
              assignees(first:50){ nodes{ login } }
            }
          }
          fieldValues(first:50){
            nodes{
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue{ name }
              ... on ProjectV2ItemFieldTextValue{ text }
            }
          }
        }
      }
    }
    '''


def _infer_priority_from_fieldnodes(field_nodes: List[Dict]) -> Optional[str]:
    if not field_nodes:
        return None
    # Collect single-select names and look for priority keywords
    priority_set = {"high", "medium", "low", "urgent", "critical"}
    for n in field_nodes:
        if n.get("__typename") == "ProjectV2ItemFieldSingleSelectValue":
            val = n.get("name")
            if val and val.strip().lower() in priority_set:
                # capitalize
                return val
    return None


def collect(project_item_id: str, token: Optional[str] = None) -> Dict:
    """Collect metadata for a project item by its ProjectV2 item id.

    Returns dict matching collected_tasks.json spec (without writing file).
    """
    q = _build_query_for_item()
    data = execute_query(q, {"id": project_item_id}, token=token)
    node = data.get("node")
    if not node:
        raise Exception(f"Project item {project_item_id} not found")

    content = node.get("content") or {}
    content_type = content.get("__typename")
    if content_type != "Issue":
        raise UnsupportedProjectItemError(
            f"Project item {project_item_id} has unsupported content type "
            f"{content_type or 'DraftIssue'}; only Issue items are collected"
        )
    issue = content
    issue_id = issue.get("id")
    issue_number = issue.get("number")
    title = issue.get("title")
    description = issue.get("body")
    status = None
    created_at = issue.get("createdAt")
    updated_at = issue.get("updatedAt")
    repository = (issue.get("repository") or {}).get("nameWithOwner")
    comments_count = None
    labels = []
    assignees = []
    if issue.get("comments"):
        comments_count = issue.get("comments", {}).get("totalCount")
    if issue.get("labels"):
        labels = [n.get("name") for n in issue.get("labels", {}).get("nodes", []) if n.get("name")]
    if issue.get("assignees"):
        assignees = [u.get("login") for u in issue.get("assignees", {}).get("nodes", []) if u.get("login")]

    field_nodes = node.get("fieldValues", {}).get("nodes", [])
    # infer status from single-select field values as in status_monitor
    status = None
    single_selects = [n.get("name") for n in field_nodes if n.get("__typename") == "ProjectV2ItemFieldSingleSelectValue" and n.get("name")]
    known_statuses = {"todo": "Todo", "in progress": "In Progress", "in_progress": "In Progress", "inprogress": "In Progress", "done": "Done", "closed": "Done"}
    for s in single_selects:
        key = s.strip().lower()
        if key in known_statuses:
            status = known_statuses[key]
            break
    if not status and len(single_selects) == 1:
        status = single_selects[0]

    priority = _infer_priority_from_fieldnodes(field_nodes)

    detected_start_time = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "project_item_id": project_item_id,
        "issue_id": issue_id,
        "issue_number": issue_number,
        "title": title,
        "description": description,
        "status": status,
        "priority": priority,
        "labels": labels,
        "assignees": assignees,
        "comments_count": comments_count,
        "created_at": created_at,
        "updated_at": updated_at,
        "repository": repository,
        "detected_start_time": detected_start_time,
    }
