from typing import Dict, Optional

from .repositories import StatusMappingRepository

VALID_LOGICAL_STATES = {"NOT_STARTED", "ACTIVE", "DONE", "OTHER"}
_repository = StatusMappingRepository()


def set_status_mapping(project_id: str, mapping: Dict[str, str]) -> None:
    """Replace a project's mapping from GitHub option names to logical states."""
    normalized = {}
    for option_name, logical_state in mapping.items():
        state = logical_state.strip().upper()
        if state not in VALID_LOGICAL_STATES:
            raise ValueError(f"Invalid logical state {logical_state!r}")
        normalized[option_name] = state
    _repository.replace(project_id, normalized)


def map_status(project_id: str, status_option_name: Optional[str]) -> str:
    return _repository.get_logical(project_id, status_option_name)


def get_status_mapping(project_id: str) -> Dict[str, str]:
    """Return the saved GitHub option-name to logical-state mapping."""
    return _repository.get_mapping(project_id)
