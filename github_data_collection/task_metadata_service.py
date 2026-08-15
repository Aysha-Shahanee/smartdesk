"""Full metadata retrieval and persistence, separate from event detection."""

import logging
from typing import Optional

from .collectors.metadata_collector import collect
from .repositories import ActiveTaskRepository, CollectedTaskRepository


logger = logging.getLogger("smartdesk.collector.github.metadata")


class TaskMetadataService:
    def __init__(self, collected=None, active=None, fetcher=collect,
                 on_lifecycle_started=None, connected_github_login=None):
        self.collected = collected or CollectedTaskRepository()
        self.active = active or ActiveTaskRepository()
        self.fetcher = fetcher
        self.on_lifecycle_started = on_lifecycle_started
        self.connected_github_login = (
            connected_github_login.strip().casefold()
            if connected_github_login and connected_github_login.strip()
            else None
        )

    def _is_owned(self, metadata: dict) -> bool:
        """Require assignee membership when SmartDesk supplied a GitHub login."""
        if self.connected_github_login is None:
            return True
        assignees = {
            str(login).strip().casefold()
            for login in metadata.get("assignees") or []
            if str(login).strip()
        }
        project_item_id = metadata.get("project_item_id")
        if not assignees:
            logger.info("Skipped %s — unassigned", project_item_id)
            return False
        if self.connected_github_login not in assignees:
            logger.info(
                "Skipped %s — not assigned to connected user", project_item_id
            )
            return False
        return True

    def _notify_started(self, metadata: dict, lifecycle_id: int) -> None:
        metadata["collector_lifecycle_id"] = lifecycle_id
        if self.on_lifecycle_started:
            try:
                self.on_lifecycle_started(metadata)
            except Exception:
                logger.exception("Lifecycle-start callback failed for %s", metadata.get("project_item_id"))

    def _started(self, metadata: dict) -> None:
        lifecycle_id = self.collected.insert(metadata)
        self.active.add(metadata)
        self._notify_started(metadata, lifecycle_id)

    def task_started(self, project_item_id: str, token: Optional[str] = None) -> dict:
        return self.synchronize_active(project_item_id, token=token)

    def task_completed(self, project_item_id: str, token: Optional[str] = None) -> dict:
        metadata = self._fetch(project_item_id, token)
        self.collected.complete_open(project_item_id, metadata)
        self.active.remove(project_item_id)
        return metadata

    def synchronize_active(self, project_item_id: str, is_new: bool | None = None,
                           token: Optional[str] = None) -> dict:
        metadata = self._fetch(project_item_id, token)
        lifecycle_id = self.collected.update_open(project_item_id, metadata)
        if lifecycle_id is None:
            if not self._is_owned(metadata):
                self.active.remove(project_item_id)
                return metadata
            self._started(metadata)
        else:
            self.active.add(metadata)
            self._notify_started(metadata, lifecycle_id)
        return metadata

    def synchronize_inactive(self, project_item_id: str,
                             token: Optional[str] = None) -> None:
        """Remove current-active state and close an orphaned open lifecycle."""
        self.active.remove(project_item_id)
        if self.collected.has_open(project_item_id):
            metadata = self._fetch(project_item_id, token)
            self.collected.complete_open(project_item_id, metadata)

    def _fetch(self, project_item_id: str, token: Optional[str]) -> dict:
        try:
            return self.fetcher(project_item_id, token=token)
        except TypeError as exc:
            if "token" not in str(exc):
                raise
            return self.fetcher(project_item_id)
