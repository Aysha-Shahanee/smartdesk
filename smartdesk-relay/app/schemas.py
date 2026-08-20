from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RegistrationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["register"]
    installation_id: int = Field(gt=0)
    token: str = Field(min_length=1, max_length=256)


class ProjectItem(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    node_id: str = Field(min_length=1, max_length=256)
    project_node_id: str | None = Field(default=None, max_length=256)
    content_node_id: str | None = Field(default=None, max_length=256)


class Installation(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: int = Field(gt=0)


class ProjectsV2ItemWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    action: str = Field(min_length=1, max_length=64)
    installation: Installation
    projects_v2_item: ProjectItem


class RelayNotification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["github_project_item_changed"] = "github_project_item_changed"
    installation_id: int
    project_item_node_id: str
    project_node_id: str | None = None
    content_node_id: str | None = None
    action: str


def notification_from_payload(payload: object) -> RelayNotification:
    event = ProjectsV2ItemWebhook.model_validate(payload)
    item = event.projects_v2_item
    return RelayNotification(
        installation_id=event.installation.id,
        project_item_node_id=item.node_id,
        project_node_id=item.project_node_id,
        content_node_id=item.content_node_id,
        action=event.action,
    )

