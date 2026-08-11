// Canonical time handling for activity segments.
//
// IMPORTANT: the API field is called `start_time_utc`/`end_time_utc` but does
// NOT hold UTC. The segment builder writes `local_date` as
// `start_time.date().isoformat()` — a bare date extraction with no zone
// conversion — so the stored value is already local wall time and arrives as a
// naive ISO string ("2026-07-31T00:36:53.447862"). Treating it as UTC shifts
// every timestamp by the zone offset. Parse it as local, which is what the
// JS Date constructor already does for a zone-less ISO string.

/** Parse a segment timestamp as local wall time. Returns null if unusable. */
export function parseSegmentTime(value?: string | null): Date | null {
  if (!value) return null;
  // Strip any trailing zone designator so the value is unambiguously parsed
  // as local, even if a future backend starts emitting one.
  const naive = value.replace(/(Z|[+-]\d{2}:?\d{2})$/, '');
  const d = new Date(naive);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "14:05" style clock label for a segment timestamp. */
export function formatSegmentTime(value?: string | null): string {
  const d = parseSegmentTime(value);
  return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
}

/** Duration in seconds between two segment timestamps (0 when unparseable). */
export function segmentDurationSec(start?: string | null, end?: string | null): number {
  const s = parseSegmentTime(start);
  const e = parseSegmentTime(end);
  if (!s || !e) return 0;
  return Math.max(0, (e.getTime() - s.getTime()) / 1000);
}

/** Compact "2h 15m" / "45m" duration label. */
export function formatDuration(sec: number): string {
  const total = Math.max(0, Math.round(sec));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${total}s`;
}

/** Events from the calendar API carry a real offset, so parse them normally. */
export function formatEventTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? '—'
    : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function capitalize(s: string): string {
  if (!s) return '';
  return s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
}

/** YYYY-MM-DD from a Date's *local* fields. */
export function toDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/**
 * Today in local time.
 *
 * `new Date().toISOString().split('T')[0]` returns the UTC date, which is the
 * previous day for every local time before the UTC offset — in Asia/Colombo
 * (+05:30) that is midnight to 05:30 every night. The app opened on yesterday's
 * data while the backend, which uses `datetime.now().date()`, considered it
 * today.
 */
export function todayString(): string {
  return toDateString(new Date());
}

/** Shift a YYYY-MM-DD date by whole days, staying in local time. */
export function shiftDate(date: string, days: number): string {
  const d = new Date(`${date}T00:00:00`); // local midnight, not UTC midnight
  d.setDate(d.getDate() + days);
  return toDateString(d);
}
