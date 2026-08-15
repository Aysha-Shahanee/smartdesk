// Focus scoring, as the backend already defines it.
//
// `activity_segments.focus_score` is written per segment by
// backend/app/services/focus_scorer.py — a 0..1 measure of sustained,
// uninterrupted presence on one thing, from three measured signals (presence,
// unbroken time, switching churn) plus two bounded adjustments. It is not a
// productivity verdict.
//
// A period's score is the duration-weighted mean of the segments inside it.
// That is the definition `day_focus` uses in
// backend/app/services/recommendations/features.py, so the Dashboard, the
// Timeline, the recommendations and the report all quote one number instead of
// four that nearly agree.

/** How far a period's focus is actually backed by scored segments. */
export interface FocusSummary {
  /** Duration-weighted mean, 0..1. Null when nothing in the period is scored. */
  score: number | null;
  /** Active seconds carrying a score — the weight behind `score`. */
  scoredSec: number;
  /** Active seconds in the period, scored or not. */
  totalSec: number;
  /** `scoredSec / totalSec`, 0..1. */
  coverage: number;
  /** Number of scored segments. */
  segments: number;
}

/** Seconds a segment covers, preferring the stored column the backend weights by. */
const segmentSeconds = (seg: any): number => {
  if (typeof seg.duration_sec === 'number') return Math.max(0, seg.duration_sec);
  const start = Date.parse(String(seg.start_time_utc ?? '').replace(/(Z|[+-]\d{2}:?\d{2})$/, ''));
  const end = Date.parse(String(seg.end_time_utc ?? '').replace(/(Z|[+-]\d{2}:?\d{2})$/, ''));
  return Number.isNaN(start) || Number.isNaN(end) ? 0 : Math.max(0, (end - start) / 1000);
};

const isScored = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

/**
 * Duration-weighted focus across a set of segments.
 *
 * Weighted rather than averaged flat because segment lengths span three orders
 * of magnitude — 0.7s to the 900s splitter cap. Unweighted, a four-second
 * alt-tab would count for as much as a quarter-hour of work.
 *
 * Idle, locked and gap segments are dropped rather than scored: the scorer
 * returns a hard 0.0 for them because nobody was present, so leaving them in
 * would report a day of ordinary work as broken focus in proportion to how
 * long the machine sat unattended. Filtering here rather than at each call
 * site keeps every view on the same population.
 *
 * Segments with a NULL score are excluded rather than counted as zero — an
 * unscored segment is missing data, not an absence of focus. In the recorded
 * history these are sub-second window blips: 6,457 of them totalling 79
 * minutes, against the 187 hours that are scored, so `coverage` sits above
 * 0.97 on a normal day. It is returned rather than assumed so a caller can say
 * what its number rests on.
 */
export function summarizeFocus(segments: any[]): FocusSummary {
  let weighted = 0;
  let scoredSec = 0;
  let totalSec = 0;
  let scored = 0;

  for (const seg of segments) {
    if ((seg.state ?? 'active') !== 'active') continue;
    const seconds = segmentSeconds(seg);
    if (seconds <= 0) continue;
    totalSec += seconds;
    if (!isScored(seg.focus_score)) continue;
    weighted += seg.focus_score * seconds;
    scoredSec += seconds;
    scored += 1;
  }

  return {
    score: scoredSec > 0 ? weighted / scoredSec : null,
    scoredSec,
    totalSec,
    coverage: totalSec > 0 ? scoredSec / totalSec : 0,
    segments: scored,
  };
}

/* Scored seconds an hour needs before its focus is worth plotting. An hour
   holding one two-minute glance is not a reading about that hour, however well
   the glance happened to score — the same guard the backend puts on
   `best_hour` / `worst_hour`, at a lower bar because this is a chart point
   rather than a claim about the day's best hour. */
export const HOUR_MIN_SCORED_SEC = 300;

/**
 * Focus per clock hour, 0..1, with null for hours that have too little scored
 * activity to say anything.
 *
 * A segment is split across every hour it touches rather than billed whole to
 * the hour it started in, so this lines up with the activity bars it is drawn
 * over. Segments are capped at 900s so the two conventions rarely disagree,
 * but the chart is read against those bars and should be measured like them.
 */
export function focusByHour(segments: any[]): (number | null)[] {
  const weighted = new Array(24).fill(0);
  const seconds = new Array(24).fill(0);

  for (const seg of segments) {
    if ((seg.state ?? 'active') !== 'active') continue;
    if (!isScored(seg.focus_score)) continue;

    const raw = String(seg.start_time_utc ?? '').replace(/(Z|[+-]\d{2}:?\d{2})$/, '');
    const rawEnd = String(seg.end_time_utc ?? '').replace(/(Z|[+-]\d{2}:?\d{2})$/, '');
    const start = new Date(raw);
    const end = new Date(rawEnd);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) continue;

    let cursor = start.getTime();
    const endMs = end.getTime();
    while (cursor < endMs) {
      const at = new Date(cursor);
      const hourEnd = new Date(
        at.getFullYear(), at.getMonth(), at.getDate(), at.getHours() + 1, 0, 0, 0
      ).getTime();
      const sliceEnd = Math.min(hourEnd, endMs);
      const slice = (sliceEnd - cursor) / 1000;
      weighted[at.getHours()] += seg.focus_score * slice;
      seconds[at.getHours()] += slice;
      cursor = sliceEnd;
    }
  }

  return seconds.map((sec, hour) =>
    sec >= HOUR_MIN_SCORED_SEC ? weighted[hour] / sec : null
  );
}

/** The 0..100 figure the UI shows, from a 0..1 score. */
export const focusOutOf100 = (score: number): number => Math.round(score * 100);
