CREATE TABLE IF NOT EXISTS github_initial_predictions (
    id INTEGER PRIMARY KEY,
    collector_lifecycle_id INTEGER NOT NULL UNIQUE,
    user_id VARCHAR NOT NULL,
    project_id VARCHAR NOT NULL,
    project_item_id VARCHAR NOT NULL,
    issue_id VARCHAR NOT NULL,
    title VARCHAR,
    description VARCHAR,
    labels_json VARCHAR,
    repository VARCHAR,
    started_at VARCHAR NOT NULL,
    predicted_low_hours FLOAT,
    predicted_typical_hours FLOAT,
    predicted_high_hours FLOAT,
    model_version VARCHAR,
    predicted_at VARCHAR NOT NULL,
    prediction_status VARCHAR NOT NULL,
    prediction_error VARCHAR
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_github_initial_predictions_lifecycle
    ON github_initial_predictions (collector_lifecycle_id);
CREATE INDEX IF NOT EXISTS ix_github_initial_predictions_user
    ON github_initial_predictions (user_id);
CREATE INDEX IF NOT EXISTS ix_github_initial_predictions_project
    ON github_initial_predictions (project_id);
CREATE INDEX IF NOT EXISTS ix_github_initial_predictions_item
    ON github_initial_predictions (project_item_id);
