from typing import Dict

from pydantic import BaseModel


class GitHubProjectSelection(BaseModel):
    owner: str
    project_number: int
    project_id: str
    title: str | None = None


class GitHubStatusMappingUpdate(BaseModel):
    mapping: Dict[str, str]
