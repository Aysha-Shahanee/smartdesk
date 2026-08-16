"""Independent GitHub Projects v2 collection package for SmartDesk."""

from .initial_sync import initial_sync
from .github_app import build_installation_url, create_app_jwt, create_installation_token, get_installation
from .project_service import discover_projects, get_status_options
from .status_mapping import get_status_mapping, map_status, set_status_mapping
from .webhook_handler import get_event_identity, handle_github_webhook_event

__all__ = [
    "build_installation_url",
    "create_app_jwt",
    "create_installation_token",
    "discover_projects",
    "get_installation",
    "get_status_options",
    "get_status_mapping",
    "get_event_identity",
    "handle_github_webhook_event",
    "initial_sync",
    "map_status",
    "set_status_mapping",
]
