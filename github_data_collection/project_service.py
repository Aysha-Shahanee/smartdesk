"""Reusable GitHub Projects v2 discovery APIs."""

from typing import Dict, List

from .github_client import execute_query


def discover_projects(token: str) -> List[Dict]:
    query = """
    query {
      viewer {
        login
        projectsV2(first: 50) { nodes { id number title owner { ... on User { login } ... on Organization { login } } } }
        organizations(first: 50) {
          nodes {
            login
            projectsV2(first: 50) { nodes { id number title } }
          }
        }
      }
    }
    """
    viewer = execute_query(query, token=token).get("viewer") or {}
    projects = []
    for project in (viewer.get("projectsV2") or {}).get("nodes") or []:
        owner = project.get("owner") or {}
        projects.append({
            "project_id": project.get("id"),
            "number": project.get("number"),
            "title": project.get("title"),
            "owner": owner.get("login") or viewer.get("login"),
        })
    for organization in (viewer.get("organizations") or {}).get("nodes") or []:
        for project in (organization.get("projectsV2") or {}).get("nodes") or []:
            projects.append({
                "project_id": project.get("id"),
                "number": project.get("number"),
                "title": project.get("title"),
                "owner": organization.get("login"),
            })
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
