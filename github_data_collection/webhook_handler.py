"""Framework-neutral GitHub webhook entry point.

The host backend is responsible for HTTP routing, signature validation, and
obtaining an installation token. Pass that token to this module after those
steps have completed.
"""

from typing import Dict, Optional

from .repositories import ProjectItemStateRepository, WebhookDeliveryRepository
from .status_mapping import map_status
from .task_metadata_service import TaskMetadataService


def _header(headers: Dict, name: str) -> Optional[str]:
    wanted = name.casefold()
    for key, value in (headers or {}).items():
        if key.casefold() == wanted:
            return value
    return None


def _nested(data: Dict, *path):
    value = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _event_values(payload: Dict):
    item = payload.get("projects_v2_item") or payload.get("project_v2_item") or {}
    changes = payload.get("changes") or {}
    field_change = changes.get("field_value") or changes.get("fieldValue") or {}
    project_id = (
        item.get("project_node_id") or item.get("project_id")
        or _nested(item, "project", "node_id") or payload.get("project_id")
    )
    item_id = item.get("node_id") or item.get("id") or payload.get("project_item_id")
    old_name = _nested(field_change, "from", "name")
    new_name = (
        _nested(field_change, "to", "name") or field_change.get("name")
        or _nested(item, "field_value", "name") or item.get("status_option_name")
    )
    return project_id, item_id, old_name, new_name


def get_event_identity(payload: Dict) -> tuple[Optional[str], Optional[str]]:
    """Return the project and item IDs without exposing payload parsing internals."""
    project_id, item_id, _, _ = _event_values(payload)
    return project_id, item_id


def handle_github_webhook_event(payload: dict, headers: dict,
                                token: Optional[str] = None,
                                metadata_service=None,
                                state_repository=None,
                                delivery_repository=None,
                                status_mapper=map_status) -> None:
    """Process a projects_v2_item event; safe to call for unrelated events."""
    event_name = _header(headers, "X-GitHub-Event")
    if event_name and event_name not in {"projects_v2_item", "project_v2_item"}:
        return

    delivery_id = _header(headers, "X-GitHub-Delivery")
    deliveries = delivery_repository or WebhookDeliveryRepository()
    if deliveries.is_processed(delivery_id):
        return

    project_id, item_id, payload_old_name, new_name = _event_values(payload)
    if not project_id or not item_id or new_name is None:
        deliveries.mark_processed(delivery_id)
        return

    states = state_repository or ProjectItemStateRepository()
    previous = states.get(item_id)
    old_name = previous["status_option_name"] if previous else payload_old_name
    old_logical = previous["logical_status"] if previous else status_mapper(project_id, old_name)
    new_logical = status_mapper(project_id, new_name)

    # State equality makes redeliveries idempotent even when no delivery ID exists.
    if previous and previous["status_option_name"] == new_name and previous["logical_status"] == new_logical:
        deliveries.mark_processed(delivery_id)
        return

    service = metadata_service or TaskMetadataService()
    if old_logical != "ACTIVE" and new_logical == "ACTIVE":
        service.task_started(item_id, token=token)
    elif old_logical == "ACTIVE" and new_logical == "DONE":
        service.task_completed(item_id, token=token)

    states.upsert(item_id, project_id, new_name, new_logical)
    deliveries.mark_processed(delivery_id)
