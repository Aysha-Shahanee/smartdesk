// Continuous stretches of work, stitched back out of activity segments.
//
// The segment splitter cuts on every app change, every IDE/browser session edge
// and at its 900s cap, so one unbroken hour of work arrives as a dozen rows.
// Anything measuring sustained attention has to undo that first — this is where
// that happens, once, for every view that needs it.

import { parseSegmentTime } from './time';

/* Segments this close together are treated as one continuous stretch. Without a
   merge tolerance a day of normal alt-tabbing looks like hundreds of one-minute
   "sessions" and no block ever exceeds a couple of minutes. */
export const BLOCK_GAP_SEC = 120;

/* A merged block at least this long counts as deep work. 25 minutes is the
   conventional threshold for an uninterrupted focus stretch, and matches
   DEEP_BLOCK_MIN_SEC in the backend's recommendations engine.

   Note there is no focus gate here, and that is deliberate rather than an
   omission. The backend pairs its length test with `block focus >= focus p75`,
   but that percentile is taken over `activity_window_patterns.avg_focus_score`,
   a population where an unworked 10-minute window scores a literal 0 — three
   quarters of the recorded windows are zeros, so the p75 evaluates to 0.0 and
   the gate passes everything. Copying an inert gate here would imply a
   selectivity that is not being applied anywhere. Length is the whole test, in
   both places, until that population is fixed. */
export const DEEP_WORK_MIN_SEC = 25 * 60;

export interface WorkBlock {
  start: Date;
  end: Date;
  seconds: number;
  /** Duration-weighted focus over the block's scored segments, or null. */
  focus: number | null;
}

/**
 * Merge active segments into continuous blocks.
 *
 * Non-active segments are skipped rather than treated as terminators: the gap
 * test subsumes them. A short idle leaves a short gap between the active
 * segments around it and the block survives, while a real absence leaves a long
 * one and it does not — which matters because the OS collector marks idle after
 * 120s of no input, something anyone reading the screen trips constantly.
 */
export function buildBlocks(segments: any[]): WorkBlock[] {
  const active = segments
    .filter(seg => (seg.state ?? 'active') === 'active')
    .map(seg => {
      const start = parseSegmentTime(seg.start_time_utc);
      const end = parseSegmentTime(seg.end_time_utc);
      if (!start || !end || end <= start) return null;
      const focus = typeof seg.focus_score === 'number' ? seg.focus_score : null;
      return { start, end, focus };
    })
    .filter((seg): seg is { start: Date; end: Date; focus: number | null } => seg !== null)
    .sort((a, b) => a.start.getTime() - b.start.getTime());

  const blocks: WorkBlock[] = [];
  let weighted = 0;
  let scoredSec = 0;

  const close = () => {
    const tail = blocks[blocks.length - 1];
    if (tail) tail.focus = scoredSec > 0 ? weighted / scoredSec : null;
  };

  for (const seg of active) {
    const tail = blocks[blocks.length - 1];
    const contiguous =
      tail !== undefined &&
      (seg.start.getTime() - tail.end.getTime()) / 1000 <= BLOCK_GAP_SEC;

    if (contiguous && tail) {
      // Segments can overlap when two collectors saw the same window.
      if (seg.end > tail.end) tail.end = seg.end;
      tail.seconds = (tail.end.getTime() - tail.start.getTime()) / 1000;
    } else {
      close();
      weighted = 0;
      scoredSec = 0;
      blocks.push({
        start: seg.start,
        end: seg.end,
        seconds: (seg.end.getTime() - seg.start.getTime()) / 1000,
        focus: null,
      });
    }

    if (seg.focus !== null) {
      const seconds = (seg.end.getTime() - seg.start.getTime()) / 1000;
      weighted += seg.focus * seconds;
      scoredSec += seconds;
    }
  }
  close();

  return blocks;
}

/**
 * Active time split into deep work and everything else, in seconds.
 *
 * "Shallow" is the remainder rather than its own measurement: every active
 * second is in exactly one of the two, so the pair always sums to the day's
 * active time and cannot quietly disagree with it.
 */
export function deepWorkSplit(segments: any[]): { deepSec: number; shallowSec: number } {
  let deepSec = 0;
  let totalSec = 0;
  for (const block of buildBlocks(segments)) {
    totalSec += block.seconds;
    if (block.seconds >= DEEP_WORK_MIN_SEC) deepSec += block.seconds;
  }
  return { deepSec, shallowSec: Math.max(0, totalSec - deepSec) };
}
