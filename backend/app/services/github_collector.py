import json
import logging
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path
import requests

from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.db.github_commit import GitHubCommitRecord

logger = logging.getLogger("smartdesk.github_collector")


class GitHubCollectorJob:
    def __init__(self) -> None:
        self._timer: threading.Timer | None = None
        self._running = False
        self._lock = threading.Lock()
        self._config_file = Path(settings.GITHUB_CONFIG_FILE)
        self._interval_sec = settings.GITHUB_SYNC_INTERVAL_SEC

        # Config state
        self._repos: list[str] = []
        self._token: str | None = None
        self._load_config()

    def start(self) -> None:
        with self._lock:
            if self._running:
                logger.warning("GitHubCollectorJob already running — ignoring start().")
                return
            self._running = True
        logger.info("GitHubCollectorJob started (interval=%ds).", self._interval_sec)
        self._schedule()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("GitHubCollectorJob stopped.")

    def reload_config(self) -> None:
        logger.info("GitHubCollectorJob reloading config from file.")
        self._load_config()

    def sync_now(self, db: DbSession) -> dict:
        """Manually trigger a sync execution synchronously. Returns sync status."""
        logger.info("GitHubCollectorJob manual sync triggered.")
        return self._run_sync(db)

    def _load_config(self) -> None:
        if not self._config_file.exists():
            self._repos = []
            self._token = None
            return

        try:
            data = json.loads(self._config_file.read_text(encoding="utf-8"))
            self._repos = [r.strip() for r in data.get("repos", []) if r.strip()]
            self._token = data.get("token") or None
        except Exception:
            logger.exception("Failed to load github configuration from %s", self._config_file)
            self._repos = []
            self._token = None

    def _schedule(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval_sec, self._tick)
            self._timer.daemon = True
            self._timer.name = "smartdesk-github-collector"
            self._timer.start()

    def _tick(self) -> None:
        try:
            db: DbSession = SessionLocal()
            try:
                self._run_sync(db)
            finally:
                db.close()
        except Exception:
            logger.exception("GitHubCollectorJob encountered an error during tick.")
        finally:
            self._schedule()

    def _run_sync(self, db: DbSession) -> dict:
        if not self._repos:
            logger.debug("No GitHub repositories configured for collection.")
            return {"success": True, "message": "No repositories configured.", "added_commits": 0}

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "SmartDesk-GitHub-Collector",
        }
        if self._token:
            headers["Authorization"] = f"token {self._token}"

        total_new_commits = 0
        repo_results = {}

        for repo in self._repos:
            try:
                added = self._fetch_and_store_commits(db, repo, headers)
                total_new_commits += added
                repo_results[repo] = {"success": True, "added": added}
            except Exception as exc:
                logger.error("Failed to sync commits for %s: %s", repo, exc)
                repo_results[repo] = {"success": False, "error": str(exc)}

        return {
            "success": True,
            "added_commits": total_new_commits,
            "repos": repo_results,
        }

    def _fetch_and_store_commits(self, db: DbSession, repo: str, headers: dict) -> int:
        url = f"https://api.github.com/repos/{repo}/commits"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 404:
            logger.error("Repository %s not found or unauthorized.", repo)
            raise ValueError(f"Repository not found or unauthorized: {repo}")
            
        response.raise_for_status()
        commits = response.json()
        
        if not isinstance(commits, list):
            logger.error("Unexpected response format from GitHub API for %s: %s", repo, commits)
            raise ValueError("Unexpected response format from GitHub API")

        new_commits_count = 0
        for item in commits:
            sha = item.get("sha")
            if not sha:
                continue

            # Check database
            exists = db.query(GitHubCommitRecord).filter(GitHubCommitRecord.sha == sha).first()
            if exists:
                # API returns commits newest first. If we hit an existing commit, we can stop scanning.
                break

            commit_info = item.get("commit", {})
            author_info = commit_info.get("author", {})
            
            record = GitHubCommitRecord(
                sha=sha,
                user_id=settings.DEFAULT_USER_ID,
                repo=repo,
                message=commit_info.get("message", "No commit message"),
                author_name=author_info.get("name"),
                author_email=author_info.get("email"),
                committed_at=author_info.get("date"),
                collected_at=datetime.now(timezone.utc).isoformat()
            )
            db.add(record)
            new_commits_count += 1

        if new_commits_count > 0:
            db.commit()
            logger.info("Stored %d new commits for %s.", new_commits_count, repo)
        else:
            logger.info("No new commits found for %s.", repo)

        return new_commits_count


# Module level singleton instance
github_collector_job = GitHubCollectorJob()
