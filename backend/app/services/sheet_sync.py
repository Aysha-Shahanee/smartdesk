"""Mirror label corrections to the shared Google Sheet.

The database is the source of truth. This is a best-effort mirror so a team
can pool training labels: every correction lands in ``activity_segment_labels``
first and is only then queued for the sheet, so a network failure can never
lose a label.

Three things the previous inline implementation in ``categorizer`` got wrong
and this fixes:

* ``gspread.oauth()`` ran on *every* correction, rebuilding the client and
  re-reading credentials each time. The client is now built once and reused.
* The append happened inline in the request handler, so a user labelling a
  segment waited on a round trip to Google. Rows are now handed to a worker
  thread and the caller returns immediately.
* The spreadsheet key was hardcoded. It comes from settings now.

Rows that fail to upload are *not* retried forever — they are already durable
in the database, and ``scripts/export_labels_to_sheet.py`` skips segment_ids
already present, so running it reconciles anything this dropped.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, List, Optional

from app.core.config import settings

logger = logging.getLogger("smartdesk.sheet_sync")

# Column order must match scripts/export_labels_to_sheet.py and the sheet.
HEADER = [
    "timestamp", "segment_id", "user_id", "label", "embedding",
    "device_id", "app_name", "title", "detail",
]

# Rows are small individually but each carries an ~8 KB embedding, so drain in
# modest batches rather than one call per row.
_BATCH_MAX = 25
# Give up after this many consecutive failures (missing credentials, revoked
# access) instead of logging on every correction forever.
_MAX_CONSECUTIVE_FAILURES = 3


class _SheetSync:
    def __init__(self) -> None:
        self._queue: "queue.Queue[List[Any]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._client = None
        self._worksheet = None
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._disabled = False

    # -- public ------------------------------------------------------- #

    def enqueue(self, row: List[Any]) -> None:
        """Queue one row. Never raises, never blocks."""
        if not settings.ENABLE_GSHEET_SYNC or self._disabled:
            return
        try:
            self._queue.put_nowait(row)
            self._ensure_worker()
        except Exception:  # noqa: BLE001 - a mirror must not break labelling
            logger.exception("could not queue label row for sheet sync")

    def pending(self) -> int:
        """Rows waiting to be written. Exposed for tests and diagnostics."""
        return self._queue.qsize()

    # -- internals ----------------------------------------------------- #

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._run, name="sheet-sync", daemon=True
            )
            self._worker.start()

    def _resolve_worksheet(self):
        if self._worksheet is not None:
            return self._worksheet
        import gspread  # imported lazily: optional dependency at runtime

        self._client = gspread.oauth()
        spreadsheet = self._client.open_by_key(settings.GSHEET_KEY)
        try:
            self._worksheet = spreadsheet.worksheet(settings.GSHEET_WORKSHEET)
        except gspread.WorksheetNotFound:
            self._worksheet = spreadsheet.add_worksheet(
                title=settings.GSHEET_WORKSHEET, rows=1000, cols=len(HEADER)
            )
            self._worksheet.append_row(HEADER, value_input_option="RAW")
        return self._worksheet

    def _run(self) -> None:
        while True:
            try:
                first = self._queue.get(timeout=30)
            except queue.Empty:
                return  # idle; _ensure_worker starts a fresh one on demand

            batch = [first]
            while len(batch) < _BATCH_MAX:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break

            try:
                self._resolve_worksheet().append_rows(
                    batch, value_input_option="RAW"
                )
                self._consecutive_failures = 0
                logger.info("mirrored %d label row(s) to the sheet", len(batch))
            except Exception as exc:  # noqa: BLE001
                self._consecutive_failures += 1
                # Force re-auth next time; a stale client is a common cause.
                self._worksheet = None
                self._client = None
                logger.warning(
                    "sheet sync failed for %d row(s) (%s). The labels are safe in "
                    "the database; run scripts/export_labels_to_sheet.py to "
                    "reconcile.", len(batch), exc,
                )
                if self._consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                    self._disabled = True
                    logger.error(
                        "sheet sync disabled after %d consecutive failures; "
                        "restart the backend once credentials are fixed "
                        '(python -c "import gspread; gspread.oauth()")',
                        self._consecutive_failures,
                    )
                    return
            finally:
                for _ in batch:
                    self._queue.task_done()


sheet_sync = _SheetSync()
