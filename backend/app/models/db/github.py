from sqlalchemy import Column, Float, Integer, String

from app.core.database import Base


class GitHubConnectionRecord(Base):
    __tablename__ = "github_connections"

    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, index=True, nullable=False)
    github_login = Column(String, nullable=True)
    installation_id = Column(Integer, unique=True, index=True, nullable=True)
    selected_owner = Column(String, nullable=True)
    selected_project_number = Column(Integer, nullable=True)
    selected_project_id = Column(String, unique=True, index=True, nullable=True)
    selected_project_title = Column(String, nullable=True)
    connection_status = Column(String, nullable=False, default="disconnected")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class GitHubOAuthStateRecord(Base):
    __tablename__ = "github_oauth_states"

    id = Column(Integer, primary_key=True)
    state_hash = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    expires_at = Column(String, nullable=False)
    used_at = Column(String, nullable=True)
    created_at = Column(String, nullable=False)


class GitHubInitialPredictionRecord(Base):
    __tablename__ = "github_initial_predictions"

    id = Column(Integer, primary_key=True)
    collector_lifecycle_id = Column(Integer, unique=True, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    project_item_id = Column(String, index=True, nullable=False)
    issue_id = Column(String, nullable=False)
    issue_number = Column(Integer, nullable=True)
    title = Column(String, nullable=True)
    description = Column(String, nullable=True)
    labels_json = Column(String, nullable=True)
    repository = Column(String, nullable=True)
    started_at = Column(String, nullable=False)
    predicted_low_hours = Column(Float, nullable=True)
    predicted_typical_hours = Column(Float, nullable=True)
    predicted_high_hours = Column(Float, nullable=True)
    model_version = Column(String, nullable=True)
    predicted_at = Column(String, nullable=False)
    prediction_status = Column(String, nullable=False)
    prediction_error = Column(String, nullable=True)
