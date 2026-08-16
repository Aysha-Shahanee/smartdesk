from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4


@dataclass(frozen=True)
class WorkSession:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = "local_user"
    session_start_time: datetime = field(default_factory=lambda: datetime.now().astimezone())


class SessionManager:
    def __init__(self, user_id: str = "local_user") -> None:
        self.current_session = WorkSession(user_id=user_id)

    @property
    def session_id(self) -> str:
        return self.current_session.session_id

    @property
    def user_id(self) -> str:
        return self.current_session.user_id

    @property
    def session_start_time(self) -> datetime:
        return self.current_session.session_start_time

