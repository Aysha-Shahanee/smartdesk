import pytest
from app.services.session_coordinator import SessionCoordinator
from app.models.schemas.ingest import OSEventPayload, OSEventType
from datetime import datetime

def test_os_session_open_and_close(db_session):
    coordinator = SessionCoordinator()
    
    start_payload = OSEventPayload(
        user_id="test_user",
        event=OSEventType.FOCUSED,
        app_name="TestApp",
        window_title="Test Window",
        process_id=1234,
        timestamp=datetime.utcnow()
    )
    
    response = coordinator.handle_os_event(start_payload, db_session)
    assert response.status == "opened"
    assert response.session_id is not None
    
    # Send another focused event to trigger close of previous session
    next_payload = OSEventPayload(
        user_id="test_user",
        event=OSEventType.FOCUSED,
        app_name="App2",
        window_title="Window 2",
        process_id=5678,
        timestamp=datetime.utcnow()
    )
    
    response_next = coordinator.handle_os_event(next_payload, db_session)
    assert response_next.status == "opened"
