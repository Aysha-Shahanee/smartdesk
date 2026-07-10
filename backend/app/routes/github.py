import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.db.github_commit import GitHubCommitRecord
from app.services.github_collector import github_collector_job

router = APIRouter()


# --- Pydantic Schemas ---

class GitHubConfigResponse(BaseModel):
    repos: List[str]
    has_token: bool


class GitHubConfigRequest(BaseModel):
    repos: List[str] = Field(..., description="List of repositories to monitor, format: owner/repo")
    token: Optional[str] = Field(None, description="GitHub Personal Access Token")


class CommitResponse(BaseModel):
    sha: str
    repo: str
    message: str
    author_name: Optional[str]
    author_email: Optional[str]
    committed_at: str
    collected_at: str

    class Config:
        from_attributes = True


# --- Endpoints ---

@router.get("/config", response_model=GitHubConfigResponse)
def get_github_config():
    config_file = Path(settings.GITHUB_CONFIG_FILE)
    if not config_file.exists():
        return GitHubConfigResponse(repos=[], has_token=False)

    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return GitHubConfigResponse(
            repos=data.get("repos", []),
            has_token=bool(data.get("token"))
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read GitHub config: {str(exc)}"
        )


@router.post("/config")
def update_github_config(payload: GitHubConfigRequest):
    config_file = Path(settings.GITHUB_CONFIG_FILE)
    try:
        config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Prepare content to write
        config_data = {
            "repos": [r.strip() for r in payload.repos if r.strip()],
            "token": payload.token
        }
        
        config_file.write_text(json.dumps(config_data, indent=2), encoding="utf-8")
        
        # Trigger reload of singleton job configuration
        github_collector_job.reload_config()
        
        return {"success": True, "message": "GitHub configuration updated successfully."}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save GitHub config: {str(exc)}"
        )


@router.post("/sync")
def sync_github_commits(
    db: Session = Depends(get_db)
):
    try:
        result = github_collector_job.sync_now(db)
        return result
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync commits: {str(exc)}"
        )


@router.get("/commits", response_model=List[CommitResponse])
def get_commits(
    repo: Optional[str] = Query(None, description="Filter by repository name"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    from_time: Optional[str] = Query(None, alias="from", description="ISO 8601 start timestamp"),
    to_time: Optional[str] = Query(None, alias="to", description="ISO 8601 end timestamp"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    target_user = user_id or settings.DEFAULT_USER_ID
    query = db.query(GitHubCommitRecord).filter(GitHubCommitRecord.user_id == target_user)

    if repo:
        query = query.filter(GitHubCommitRecord.repo == repo)
    if from_time:
        query = query.filter(GitHubCommitRecord.committed_at >= from_time)
    if to_time:
        query = query.filter(GitHubCommitRecord.committed_at <= to_time)

    # Order newest commits first
    commits = query.order_by(GitHubCommitRecord.committed_at.desc()).limit(limit).all()
    return commits
