import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.core.config import settings
from app.models.db.github_commit import GitHubCommitRecord
from app.services.github_collector import github_collector_job


@pytest.fixture
def temp_github_config(tmp_path, monkeypatch):
    test_file = tmp_path / "github_config_test.json"
    monkeypatch.setattr(settings, "GITHUB_CONFIG_FILE", str(test_file))
    
    # Store old path to reset later
    old_config_file = github_collector_job._config_file
    
    github_collector_job._config_file = test_file
    github_collector_job.reload_config()
    
    yield test_file
    
    # Cleanup and reset
    if test_file.exists():
        test_file.unlink()
    github_collector_job._config_file = old_config_file
    github_collector_job.reload_config()


def test_github_config_endpoints(client, temp_github_config):
    # Test GET config when file does not exist
    response = client.get("/api/v1/github/config")
    assert response.status_code == 200
    data = response.json()
    assert data["repos"] == []
    assert data["has_token"] is False

    # Test POST config
    config_payload = {
        "repos": ["owner/repo1", "owner/repo2"],
        "token": "test-pat-token"
    }
    post_response = client.post("/api/v1/github/config", json=config_payload)
    assert post_response.status_code == 200
    assert post_response.json()["success"] is True

    # Test GET config again
    response = client.get("/api/v1/github/config")
    assert response.status_code == 200
    data = response.json()
    assert data["repos"] == ["owner/repo1", "owner/repo2"]
    assert data["has_token"] is True


@patch("requests.get")
def test_github_sync_and_query_endpoints(mock_get, client, db_session, temp_github_config):
    # Setup test config
    config_payload = {
        "repos": ["owner/repo1"],
        "token": "some-token"
    }
    client.post("/api/v1/github/config", json=config_payload)

    # Mock GitHub API response with 2 commits
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "sha": "commit_sha_1",
            "commit": {
                "author": {
                    "name": "Developer One",
                    "email": "dev1@example.com",
                    "date": "2026-06-22T08:00:00Z"
                },
                "message": "First commit message"
            }
        },
        {
            "sha": "commit_sha_2",
            "commit": {
                "author": {
                    "name": "Developer Two",
                    "email": "dev2@example.com",
                    "date": "2026-06-22T08:15:00Z"
                },
                "message": "Second commit message"
            }
        }
    ]
    mock_get.return_value = mock_response

    # Trigger manual sync
    sync_response = client.post("/api/v1/github/sync")
    assert sync_response.status_code == 200
    sync_data = sync_response.json()
    assert sync_data["success"] is True
    assert sync_data["added_commits"] == 2

    # Verify commits in database directly
    commits_in_db = db_session.query(GitHubCommitRecord).all()
    assert len(commits_in_db) == 2
    shas = {c.sha for c in commits_in_db}
    assert "commit_sha_1" in shas
    assert "commit_sha_2" in shas

    # Verify querying endpoint
    query_response = client.get("/api/v1/github/commits")
    assert query_response.status_code == 200
    commits_api = query_response.json()
    assert len(commits_api) == 2
    assert commits_api[0]["sha"] == "commit_sha_2"  # Newest (08:15) first
    assert commits_api[0]["message"] == "Second commit message"
    assert commits_api[1]["sha"] == "commit_sha_1"
    assert commits_api[1]["message"] == "First commit message"

    # Trigger second sync (should not duplicate)
    # Mocking same API response (representing no new commits)
    sync_response2 = client.post("/api/v1/github/sync")
    assert sync_response2.status_code == 200
    sync_data2 = sync_response2.json()
    assert sync_data2["added_commits"] == 0

    # DB count remains 2
    assert db_session.query(GitHubCommitRecord).count() == 2
