import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.db import ActivitySegmentRecord, IDESessionRecord
from app.services.github_task_time_spent_service import GitHubTaskTimeSpentService
from app.services.github_remaining_time_service import GitHubRemainingTimeService


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


class GitHubTaskTimeSpentTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            engine, tables=[IDESessionRecord.__table__, ActivitySegmentRecord.__table__]
        )
        self.db = sessionmaker(bind=engine)()
        self.lifecycle = {
            "collector_lifecycle_id": 1,
            "user_id": "user-one",
            "repository": "Owner/Repo",
            "started_at": "2026-08-14T10:00:00Z",
        }

    def tearDown(self):
        self.db.close()

    def add_interval(
        self,
        row_id,
        start,
        end,
        *,
        state="active",
        repository="owner/repo",
        foreground=True,
        reason="foreground",
        branch=None,
    ):
        ide_id = f"ide-{row_id}"
        self.db.add(IDESessionRecord(
            id=ide_id,
            user_id="user-one",
            instance_id=f"instance-{row_id}",
            repository=repository,
            git_branch=branch,
            session_start=start,
            session_end=end,
            duration_sec=1,
            is_foreground=int(foreground),
            confirmed_by_os=int(foreground),
            collection_reason=reason,
            edit_count=0,
            save_count=0,
            lines_added=0,
            lines_deleted=0,
            file_switch_count=0,
            created_at=start,
            updated_at=end,
        ))
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        self.db.add(ActivitySegmentRecord(
            id=f"segment-{row_id}",
            user_id="user-one",
            device_id=f"device-{row_id}",
            schema_version=1,
            start_time_utc=start_dt,
            end_time_utc=end_dt,
            duration_sec=int((end_dt - start_dt).total_seconds()),
            timezone_name="UTC",
            local_date="2026-08-14",
            primary_source="ide",
            state=state,
            ide_session_id=ide_id,
        ))
        self.db.commit()

    def calculate(self, lifecycle=None, active=None):
        lifecycle = lifecycle or self.lifecycle
        active = active or [lifecycle]
        return GitHubTaskTimeSpentService(self.db, lambda: NOW).calculate(lifecycle, active)

    def test_counts_matching_active_interval_and_clips_start(self):
        self.add_interval("one", "2026-08-14T09:55:00Z", "2026-08-14T10:10:00Z")
        result = self.calculate()
        self.assertEqual(result.task_active_seconds, 600)
        self.assertEqual(result.time_attribution_status, "repository_match")

    def test_interprets_sqlite_naive_segment_times_using_persisted_timezone(self):
        self.add_interval(
            "local-time",
            "2026-08-14T15:25:00+05:30",
            "2026-08-14T15:40:00+05:30",
        )
        segment = self.db.query(ActivitySegmentRecord).filter_by(id="segment-local-time").one()
        segment.timezone_name = "Asia/Colombo"
        self.db.commit()

        result = self.calculate()

        self.assertEqual(result.task_active_seconds, 600)
        self.assertEqual(result.time_attribution_status, "repository_match")

    def test_excludes_idle_locked_gap_wrong_repo_and_background_ai(self):
        self.add_interval("idle", "2026-08-14T10:00:00Z", "2026-08-14T10:01:00Z", state="idle")
        self.add_interval("locked", "2026-08-14T10:01:00Z", "2026-08-14T10:02:00Z", state="locked")
        self.add_interval("gap", "2026-08-14T10:02:00Z", "2026-08-14T10:03:00Z", state="gap")
        self.add_interval("wrong", "2026-08-14T10:03:00Z", "2026-08-14T10:04:00Z", repository="other/repo")
        self.add_interval("ai", "2026-08-14T10:04:00Z", "2026-08-14T10:05:00Z", foreground=False, reason="background_ai")
        result = self.calculate()
        self.assertEqual(result.task_active_seconds, 0)

    def test_unrelated_missing_repository_does_not_downgrade_a_repository_match(self):
        self.add_interval("matched", "2026-08-14T10:00:00Z", "2026-08-14T10:11:00Z")
        self.add_interval(
            "unrelated-unknown",
            "2026-08-14T10:11:00Z",
            "2026-08-14T10:12:00Z",
            repository=None,
        )

        result = self.calculate()

        self.assertEqual(result.task_active_seconds, 660)
        self.assertEqual(result.time_attribution_status, "repository_match")
        self.assertEqual(result.data_status, "complete")

    def test_clips_at_completed_at_and_is_stable_across_service_instances(self):
        lifecycle = {**self.lifecycle, "completed_at": "2026-08-14T10:05:00Z"}
        self.add_interval("one", "2026-08-14T10:00:00Z", "2026-08-14T10:10:00Z")
        first = self.calculate(lifecycle, [])
        second = GitHubTaskTimeSpentService(self.db, lambda: NOW).calculate(lifecycle, [])
        self.assertEqual(first.task_active_seconds, 300)
        self.assertEqual(first.task_active_seconds, second.task_active_seconds)

    def test_merges_overlapping_intervals(self):
        self.add_interval("one", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z")
        self.add_interval("two", "2026-08-14T10:04:00Z", "2026-08-14T10:08:00Z")
        self.assertEqual(self.calculate().task_active_seconds, 480)

    def test_zero_and_negative_duration_segments_are_rejected(self):
        self.add_interval("valid", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z")
        with self.assertRaises(IntegrityError):
            self.add_interval("zero", "2026-08-14T10:05:00Z", "2026-08-14T10:05:00Z")
        self.db.rollback()
        with self.assertRaises(IntegrityError):
            self.add_interval("negative", "2026-08-14T10:07:00Z", "2026-08-14T10:06:00Z")
        self.db.rollback()

        self.assertEqual(self.calculate().task_active_seconds, 5 * 60)

    def test_strict_branch_issue_number_parser(self):
        extract = GitHubTaskTimeSpentService.extract_issue_number_from_branch_name
        accepted = {
            "issue-42-login-fix": 42,
            "issue/42-login-fix": 42,
            "gh-42-auth": 42,
            "gh/42-auth": 42,
            "fix/issue-42": 42,
            "feature/gh-57-profile": 57,
            "issue-42-fix-bug-500": 42,
        }
        rejected = (
            "feature-2026-auth", "release-2.1", "bugfix-port-5000",
            "500-error-handling", "feature/refactor-auth", "main", "dev",
        )
        for branch, expected in accepted.items():
            self.assertEqual(extract(branch), expected, branch)
        for branch in rejected:
            self.assertIsNone(extract(branch), branch)
        self.assertIsNone(extract(None))

    def test_two_active_lifecycles_without_explicit_branch_are_ambiguous(self):
        self.add_interval("main", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z", branch="main")
        other = {**self.lifecycle, "collector_lifecycle_id": 2, "issue_number": 57}
        result = self.calculate(active=[self.lifecycle, other])
        self.assertIsNone(result.task_active_seconds)
        self.assertEqual(result.time_attribution_status, "ambiguous")

    def test_multiple_active_lifecycles_are_disambiguated_per_interval(self):
        issue_42 = {**self.lifecycle, "issue_number": 42}
        issue_57 = {**self.lifecycle, "collector_lifecycle_id": 2, "issue_number": 57}
        self.add_interval("42", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z", branch="issue-42-login-fix")
        self.add_interval("57", "2026-08-14T10:05:00Z", "2026-08-14T10:12:00Z", branch="gh-57-profile")
        active = [issue_42, issue_57]

        result_42 = self.calculate(issue_42, active)
        result_57 = self.calculate(issue_57, active)

        self.assertEqual(result_42.task_active_seconds, 300)
        self.assertEqual(result_57.task_active_seconds, 420)
        self.assertEqual(result_42.time_attribution_status, "branch_match")
        self.assertEqual(result_57.time_attribution_status, "branch_match")

    def test_historical_repository_match_survives_later_same_repo_issue(self):
        issue_a = {**self.lifecycle, "issue_number": 42}
        issue_b = {
            **self.lifecycle,
            "collector_lifecycle_id": 2,
            "issue_number": 57,
            "started_at": "2026-08-14T10:20:00Z",
        }
        self.add_interval("historical-a", "2026-08-14T10:00:00Z", "2026-08-14T10:20:00Z")
        self.add_interval(
            "branch-a", "2026-08-14T10:30:00Z", "2026-08-14T10:45:00Z",
            branch="issue-42-work",
        )
        self.add_interval(
            "ambiguous", "2026-08-14T10:50:00Z", "2026-08-14T11:00:00Z",
            branch="main",
        )

        result = self.calculate(issue_a, [issue_a, issue_b])

        self.assertEqual(result.task_active_seconds, 35 * 60)
        self.assertEqual(result.time_attribution_status, "branch_match")
        self.assertEqual(result.data_status, "complete")

    def test_attribution_to_remaining_integration_preserves_only_trusted_slices(self):
        issue_a = {**self.lifecycle, "issue_number": 42}
        issue_b = {
            **self.lifecycle,
            "collector_lifecycle_id": 2,
            "issue_number": 57,
            "started_at": "2026-08-14T10:20:00Z",
        }
        self.add_interval("historical", "2026-08-14T10:00:00Z", "2026-08-14T10:20:00Z")
        self.add_interval(
            "ambiguous", "2026-08-14T10:20:00Z", "2026-08-14T10:30:00Z",
            branch="main",
        )
        self.add_interval(
            "branch-a", "2026-08-14T10:30:00Z", "2026-08-14T10:45:00Z",
            branch="issue-42-work",
        )

        spent = self.calculate(issue_a, [issue_a, issue_b])
        remaining = GitHubRemainingTimeService.calculate(1.0, spent.to_dict())

        self.assertEqual(spent.task_active_seconds, 35 * 60)
        self.assertEqual(spent.data_status, "complete")
        self.assertAlmostEqual(remaining.remaining_time_hours, 25 / 60)
        self.assertEqual(remaining.remaining_time_status, "baseline_available")

    def test_segment_crossing_second_issue_start_is_attributed_per_time_slice(self):
        issue_a = {**self.lifecycle, "issue_number": 42}
        issue_b = {
            **self.lifecycle,
            "collector_lifecycle_id": 2,
            "issue_number": 57,
            "started_at": "2026-08-14T10:20:00Z",
        }
        self.add_interval(
            "crosses-boundary", "2026-08-14T10:15:00Z", "2026-08-14T10:25:00Z",
            branch="main",
        )

        result_a = self.calculate(issue_a, [issue_a, issue_b])
        result_b = self.calculate(issue_b, [issue_a, issue_b])

        self.assertEqual(result_a.task_active_seconds, 5 * 60)
        self.assertEqual(result_a.data_status, "complete")
        self.assertIsNone(result_b.task_active_seconds)
        self.assertEqual(result_b.time_attribution_status, "ambiguous")

    def test_branch_segments_are_exclusive_between_same_repo_issues(self):
        issue_a = {**self.lifecycle, "issue_number": 42}
        issue_b = {
            **self.lifecycle,
            "collector_lifecycle_id": 2,
            "issue_number": 57,
        }
        self.add_interval(
            "only-a", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z",
            branch="issue-42-work",
        )
        self.add_interval(
            "only-b", "2026-08-14T10:05:00Z", "2026-08-14T10:12:00Z",
            branch="gh-57-work",
        )

        result_a = self.calculate(issue_a, [issue_a, issue_b])
        result_b = self.calculate(issue_b, [issue_a, issue_b])

        self.assertEqual(result_a.task_active_seconds, 5 * 60)
        self.assertEqual(result_b.task_active_seconds, 7 * 60)
        self.assertEqual(result_a.task_active_seconds + result_b.task_active_seconds, 12 * 60)

    def test_different_repositories_keep_repository_attribution(self):
        other_repo = {
            **self.lifecycle,
            "collector_lifecycle_id": 2,
            "repository": "owner/other",
            "issue_number": 57,
        }
        self.add_interval("repo", "2026-08-14T10:00:00Z", "2026-08-14T10:08:00Z")

        result = self.calculate(self.lifecycle, [self.lifecycle, other_repo])

        self.assertEqual(result.task_active_seconds, 8 * 60)
        self.assertEqual(result.time_attribution_status, "repository_match")
        self.assertEqual(result.data_status, "complete")

    def test_wrong_number_null_metadata_and_other_repository_do_not_disambiguate(self):
        issue_42 = {**self.lifecycle, "issue_number": 42}
        missing_number = {**self.lifecycle, "collector_lifecycle_id": 2, "issue_number": None}
        self.add_interval("wrong-number", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z", branch="issue-99")
        result = self.calculate(issue_42, [issue_42, missing_number])
        self.assertIsNone(result.task_active_seconds)
        self.assertEqual(result.time_attribution_status, "ambiguous")

        other_repo = {
            **self.lifecycle, "collector_lifecycle_id": 3,
            "repository": "other/repo", "issue_number": 99,
        }
        result = self.calculate(issue_42, [issue_42, missing_number, other_repo])
        self.assertEqual(result.time_attribution_status, "ambiguous")

    def test_missing_or_nonmatching_repository_is_not_reported_as_zero(self):
        self.add_interval("wrong", "2026-08-14T10:00:00Z", "2026-08-14T10:05:00Z", repository="other/repo")
        result = self.calculate()
        self.assertIsNone(result.task_active_seconds)
        self.assertEqual(result.time_attribution_status, "no_match")


if __name__ == "__main__":
    unittest.main()
