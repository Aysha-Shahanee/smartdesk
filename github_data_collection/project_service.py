"""Reusable GitHub Projects v2 discovery APIs."""

from typing import Dict, List

from .github_client import execute_query


def discover_projects(token: str, organization_login: str) -> List[Dict]:
    query = """
    query($login: String!, $cursor: String) {
      organization(login: $login) {
        login
        projectsV2(first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes { id number title }
        }
      }
    }
    """
    projects = []
    cursor = None
    while True:
        data = execute_query(
            query,
            {"login": organization_login, "cursor": cursor},
            token=token,
        )
        organization = data.get("organization")
        if not organization:
            raise LookupError(
                f"GitHub organization {organization_login!r} is not accessible to this installation"
            )
        connection = organization.get("projectsV2") or {}
        for project in connection.get("nodes") or []:
            projects.append({
                "project_id": project.get("id"),
                "number": project.get("number"),
                "title": project.get("title"),
                "owner": organization.get("login") or organization_login,
            })
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
    return projects


def get_status_options(project_id: str, token: str) -> List[Dict]:
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              ... on ProjectV2SingleSelectField {
                id
                name
                options { id name }
              }
            }
          }
        }
      }
    }
    """
    project = execute_query(query, {"id": project_id}, token=token).get("node") or {}
    for field in (project.get("fields") or {}).get("nodes") or []:
        if (field.get("name") or "").strip().casefold() == "status":
            return field.get("options") or []
    return []
