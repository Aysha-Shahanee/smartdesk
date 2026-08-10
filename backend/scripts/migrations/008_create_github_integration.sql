CREATE TABLE IF NOT EXISTS github_connections (
    id INTEGER PRIMARY KEY,
    user_id VARCHAR NOT NULL UNIQUE,
    github_login VARCHAR,
    installation_id INTEGER UNIQUE,
    selected_owner VARCHAR,
    selected_project_number INTEGER,
    selected_project_id VARCHAR UNIQUE,
    selected_project_title VARCHAR,
    connection_status VARCHAR NOT NULL DEFAULT 'disconnected',
    created_at VARCHAR NOT NULL,
    updated_at VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_github_connections_user_id
    ON github_connections (user_id);
CREATE INDEX IF NOT EXISTS ix_github_connections_installation_id
    ON github_connections (installation_id);
CREATE INDEX IF NOT EXISTS ix_github_connections_selected_project_id
    ON github_connections (selected_project_id);

CREATE TABLE IF NOT EXISTS github_oauth_states (
    id INTEGER PRIMARY KEY,
    state_hash VARCHAR NOT NULL UNIQUE,
    user_id VARCHAR NOT NULL,
    expires_at VARCHAR NOT NULL,
    used_at VARCHAR,
    created_at VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_github_oauth_states_state_hash
    ON github_oauth_states (state_hash);
CREATE INDEX IF NOT EXISTS ix_github_oauth_states_user_id
    ON github_oauth_states (user_id);
