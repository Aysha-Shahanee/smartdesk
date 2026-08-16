from typing import Dict, List

from ..database import load_previous_statuses, save_previous_statuses


def _normalize_status(s: str) -> str:
    if not s:
        return "Unknown"
    key = s.strip().lower()
    if key in {"todo", "to do"}:
        return "Todo"
    if key in {"in progress", "in_progress", "doing", "inprogress"}:
        return "In Progress"
    if key in {"done", "closed", "complete", "completed"}:
        return "Done"
    return s


def compare(current_statuses: List[Dict]) -> List[Dict]:
    """Compare previous statuses with current_statuses.

    current_statuses: list of {"project_item_id":"...","status":"..."}

    Returns list of transitions:
    [{"project_item_id":"...","old_status":"Todo","new_status":"In Progress"}, ...]

    Also updates persisted previous statuses.
    On first run (no previous state), no transitions are returned — but previous is initialized.
    """
    prev = load_previous_statuses()
    initial_run = len(prev) == 0

    # Build map from current
    cur_map = {}
    for item in current_statuses:
        pid = item.get("project_item_id")
        status = _normalize_status(item.get("status"))
        if pid:
            cur_map[pid] = status

    transitions = []

    if not initial_run:
        for pid, new_status in cur_map.items():
            old_status = prev.get(pid)
            if not old_status:
                continue
            old_norm = _normalize_status(old_status)
            if old_norm == "Todo" and new_status == "In Progress":
                transitions.append({"project_item_id": pid, "old_status": old_norm, "new_status": new_status})
            if old_norm == "In Progress" and new_status == "Done":
                transitions.append({"project_item_id": pid, "old_status": old_norm, "new_status": new_status})

    save_previous_statuses(cur_map)

    return transitions
