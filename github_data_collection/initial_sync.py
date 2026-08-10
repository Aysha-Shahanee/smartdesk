"""One-time startup/project-connection reconciliation."""

from typing import Optional

from .collectors.status_monitor import fetch_all_project_items
from .repositories import ProjectItemStateRepository
from .status_mapping import map_status
from .task_metadata_service import TaskMetadataService


def initial_sync(owner: Optional[str] = None, project_number: Optional[int] = None,
                 token: Optional[str] = None, fetcher=fetch_all_project_items,
                 metadata_service=None, state_repository=None,
                 status_mapper=map_status) -> str:
    kwargs = {"token": token}
    if owner is not None:
        kwargs["owner"] = owner
    if project_number is not None:
        kwargs["number"] = project_number
    project_id, items = fetcher(**kwargs)
    states = state_repository or ProjectItemStateRepository()
    service = metadata_service or TaskMetadataService()

    for item in items:
        item_id = item.get("project_item_id")
        if not item_id:
            continue
        previous = states.get(item_id)
        option_name = item.get("status")
        logical = status_mapper(project_id, option_name)
        if logical == "ACTIVE":
            is_new_lifecycle = previous is None or previous.get("logical_status") != "ACTIVE"
            service.synchronize_active(item_id, is_new=is_new_lifecycle, token=token)
        elif previous and previous.get("logical_status") == "ACTIVE":
            service.active.remove(item_id)
        states.upsert(item_id, project_id, option_name, logical)
    return project_id
