from typing import List, Dict

from ..database import add_active_task as _add_active_task, load_active_tasks as _load_active_tasks, remove_active_task as _remove_active_task


def load_active_tasks() -> List[Dict]:
    return _load_active_tasks()


def add_task(project_item_id: str, issue_id: str, title: str, started_at: str):
    _add_active_task(project_item_id, issue_id, title, started_at)


def remove_task(project_item_id: str):
    _remove_active_task(project_item_id)
 
