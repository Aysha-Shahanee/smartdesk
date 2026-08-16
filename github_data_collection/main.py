import logging
import time
from datetime import datetime, timezone
from typing import Dict

from .config import POLL_INTERVAL_SECONDS, settings
from .database import save_collected_task, save_sample_collection
from .collectors.project_collector import get_project_items
from .collectors.issue_collector import extract_issue_metadata
from .collectors.status_collector import extract_status
from .collectors import status_monitor
from .initial_sync import initial_sync
from .repositories import ProjectItemStateRepository
from .webhook_handler import handle_github_webhook_event


logger = logging.getLogger("smartdesk.collector.github")


def collect_once():
    """Persist a one-shot project snapshot into SQLite."""
    logger.info("Collecting GitHub project data...")
    project_data = get_project_items()
    tasks = extract_issue_metadata(project_data)
    statuses = extract_status(project_data)
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_sample_collection(tasks, statuses, collected_at)
    logger.info("Data collection completed")


def _store_collected_task(metadata: Dict):
    save_collected_task(metadata)


def run_monitor():
    settings.validate_github_access()
    logger.info("Starting GitHub Project monitor...")
    logger.info("Performing full startup sync...")
    while True:
        try:
            project_id = initial_sync()
            break
        except Exception as exc:
            logger.exception("Error during startup sync: %s", exc)
            logger.info("Retrying in %s seconds...", POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)

    logger.info("Polling every %s seconds...", POLL_INTERVAL_SECONDS)
    while True:
        try:
            logger.info("Checking GitHub Project...")
            current = status_monitor.fetch_current_statuses()
            changes = 0
            states = ProjectItemStateRepository()
            for item in current:
                previous = states.get(item["project_item_id"])
                if previous and previous["status_option_name"] == item["status"]:
                    continue
                changes += 1
                handle_github_webhook_event({
                    "project_id": item.get("project_id") or project_id,
                    "project_item_id": item["project_item_id"],
                    "projects_v2_item": {
                        "node_id": item["project_item_id"],
                        "project_node_id": item.get("project_id") or project_id,
                        "status_option_name": item["status"],
                    },
                }, {"X-GitHub-Event": "projects_v2_item"})
            if not changes:
                logger.info("No status changes detected.")

        except Exception as exc:
            logger.exception("Error during monitor loop: %s", exc)

        logger.debug("Waiting %s seconds...", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


def run_cli() -> None:
    """Configure CLI logging and start the standalone polling monitor."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    run_monitor()


if __name__ == "__main__":
    run_cli()
