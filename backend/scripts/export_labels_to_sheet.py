"""Bulk-export activity_segment_labels to the shared Google Sheet.

``Categorizer.store_user_correction`` already appends to this sheet, but one
``append_row`` per correction — fine for a trickle, unusable for a backlog:
4,477 rows would be 4,477 API calls against a 60-writes-per-minute quota.
This batches them.

Row format is identical to categorizer.py so the sheet schema is unchanged::

    timestamp, segment_id, user_id, label, embedding, device_id,
    app_name, title, detail

Note that ``title`` and ``detail`` are window titles and URLs. Everyone with
access to the sheet can read them. Only ``label`` and ``embedding`` are used
for training — see ``--minimal`` if you would rather not publish the rest.

Re-running is safe: segment_ids already in the sheet are skipped, so an
interrupted run resumes where it stopped.

Usage
-----
    # one-time, opens a browser:
    .\\venv\\Scripts\\python.exe -c "import gspread; gspread.oauth()"

    .\\venv\\Scripts\\python.exe scripts\\export_labels_to_sheet.py --dry-run
    .\\venv\\Scripts\\python.exe scripts\\export_labels_to_sheet.py --apply
    .\\venv\\Scripts\\python.exe scripts\\export_labels_to_sheet.py --apply --user-only
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "smartdesk.db"

# Same spreadsheet categorizer.py writes to.
DEFAULT_SHEET_KEY = "1G_oudT83kv-JSugqzbVE-nbLyjmQ0c7YY5EGpbLUaG8"
DEFAULT_WORKSHEET = "Labels"

# ~8.4 KB per embedding cell. 100 rows is ~0.9 MB per request, comfortably
# inside the Sheets API request ceiling while keeping the run to ~45 calls.
DEFAULT_BATCH = 100

HEADER = [
    "timestamp", "segment_id", "user_id", "label", "embedding",
    "device_id", "app_name", "title", "detail",
]


def fetch_rows(user_only: bool, minimal: bool) -> list[list[str]]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    where = "WHERE l.source = 'user'" if user_only else ""
    query = f"""
        SELECT COALESCE(l.created_at, ''), l.segment_id, COALESCE(l.user_id, ''),
               l.correct_label, COALESCE(l.embedding, ''), COALESCE(l.device_id, ''),
               COALESCE(s.app_name, ''), COALESCE(s.title, ''), COALESCE(s.detail, '')
        FROM activity_segment_labels l
        LEFT JOIN activity_segments s ON s.id = l.segment_id
        {where}
        ORDER BY l.created_at
    """
    rows = [[str(v) for v in r] for r in con.execute(query)]
    con.close()
    if minimal:
        # Blank the columns training never reads, keeping column positions so
        # the sheet schema still lines up for anyone reading it.
        for r in rows:
            r[2] = r[5] = r[6] = r[7] = r[8] = ""
    return rows


def existing_segment_ids(worksheet) -> set[str]:
    """segment_id is column B. Pulling one column avoids downloading 37 MB."""
    try:
        return {v for v in worksheet.col_values(2)[1:] if v}
    except Exception as exc:  # noqa: BLE001 - empty/new sheet is not an error
        print(f"  could not read existing ids ({exc}); assuming empty sheet")
        return set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="report without writing")
    mode.add_argument("--apply", action="store_true", help="write to the sheet")
    parser.add_argument("--user-only", action="store_true",
                        help="only source='user' rows (skip rule-generated backfill)")
    parser.add_argument("--minimal", action="store_true",
                        help="blank user_id/device_id/app_name/title/detail")
    parser.add_argument("--sheet-key", default=DEFAULT_SHEET_KEY)
    parser.add_argument("--worksheet", default=DEFAULT_WORKSHEET)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    args = parser.parse_args()

    rows = fetch_rows(args.user_only, args.minimal)
    payload_mb = sum(len(c) for r in rows for c in r) / 1_000_000
    print(f"{len(rows)} label rows selected ({payload_mb:.1f} MB)")
    if args.minimal:
        print("  --minimal: user_id/device_id/app_name/title/detail blanked")
    if not rows:
        print("nothing to export")
        return 0

    if args.dry_run:
        print(f"\nwould write to sheet {args.sheet_key} / worksheet '{args.worksheet}'")
        print(f"in {(len(rows) + args.batch_size - 1) // args.batch_size} batches "
              f"of {args.batch_size}\n")
        print("first row preview (embedding truncated):")
        for name, value in zip(HEADER, rows[0]):
            shown = value[:60] + f"... [{len(value)} chars]" if len(value) > 60 else value
            print(f"  {name:12} {shown}")
        print("\nDRY RUN - nothing written")
        return 0

    try:
        import gspread
    except ImportError:
        print("gspread is not installed: pip install gspread", file=sys.stderr)
        return 1

    try:
        client = gspread.oauth()
    except Exception as exc:  # noqa: BLE001
        print(f"Google auth failed: {exc}\n", file=sys.stderr)
        print('Authenticate once with:  python -c "import gspread; gspread.oauth()"',
              file=sys.stderr)
        return 1

    sheet = client.open_by_key(args.sheet_key)
    try:
        worksheet = sheet.worksheet(args.worksheet)
    except gspread.WorksheetNotFound:
        print(f"creating worksheet '{args.worksheet}'")
        worksheet = sheet.add_worksheet(title=args.worksheet, rows=len(rows) + 10,
                                        cols=len(HEADER))
        worksheet.append_row(HEADER, value_input_option="RAW")

    already = existing_segment_ids(worksheet)
    pending = [r for r in rows if r[1] not in already]
    print(f"{len(already)} rows already in the sheet; {len(pending)} to upload")
    if not pending:
        print("sheet is already up to date")
        return 0

    written = 0
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start:start + args.batch_size]
        for attempt in range(3):
            try:
                worksheet.append_rows(batch, value_input_option="RAW")
                break
            except Exception as exc:  # noqa: BLE001 - quota/network, worth retrying
                if attempt == 2:
                    print(f"\nfailed after {written} rows: {exc}", file=sys.stderr)
                    print("re-run the same command to resume", file=sys.stderr)
                    return 1
                wait = 5 * (attempt + 1)
                print(f"  batch failed ({exc}); retrying in {wait}s")
                time.sleep(wait)
        written += len(batch)
        print(f"  {written}/{len(pending)} rows")

    print(f"done: {written} rows appended to '{args.worksheet}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
