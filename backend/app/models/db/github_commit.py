from sqlalchemy import Column
from sqlalchemy import Index
from sqlalchemy import String

from app.core.database import Base


class GitHubCommitRecord(Base):
    __tablename__ = "github_commits"
    __table_args__ = (
        Index("ix_github_commits_user_repo", "user_id", "repo"),
        Index("ix_github_commits_committed_at", "committed_at"),
    )

    sha = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    repo = Column(String, nullable=False, index=True)

    message = Column(String, nullable=False)
    author_name = Column(String, nullable=True)
    author_email = Column(String, nullable=True)

    committed_at = Column(String, nullable=False)
    collected_at = Column(String, nullable=False)
