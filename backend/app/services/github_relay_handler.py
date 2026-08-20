"""Database-session adapter from relay notifications to GitHub processing."""

from app.core.database import SessionLocal
from app.services.github_integration_service import GitHubIntegrationService
from app.services.relay_client import RelayNotification


def process_github_relay_notification(notification: RelayNotification) -> bool:
    db = SessionLocal()
    try:
        return GitHubIntegrationService(db).process_relay_notification(
            installation_id=notification.installation_id,
            project_item_node_id=notification.project_item_node_id,
            project_node_id=notification.project_node_id,
            content_node_id=notification.content_node_id,
            action=notification.action,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
