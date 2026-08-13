export type PatternScope = 'day' | 'week' | 'month';
export type FocusLevel = 'high_focus' | 'low_focus' | 'distracted';

export interface WindowCluster {
  window_start: string;
  window_end: string;
  window_id: string;
  focus_level: FocusLevel;
  cluster_id: number | null;
  anomaly_score: number | null;
  work_ratio: number;
  learn_ratio: number;
  communication_ratio: number;
  avg_focus_score: number;
}

export interface PatternBucket {
  id: string;
  label: string;
  rangeLabel: string;
  focusLevel: FocusLevel;
  avgFocusScore: number;
  anomalyScore: number | null;
  totalWindows: number;
  counts: Record<FocusLevel, number>;
  workRatio: number;
  learnRatio: number;
  communicationRatio: number;
  start: string;
  end: string;
}

export interface FocusTrendPoint {
  label: string;
  focusScore: number;
}

const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const weekdayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const createCounts = (): Record<FocusLevel, number> => ({
  high_focus: 0,
  low_focus: 0,
  distracted: 0,
});

const parseTimestamp = (value: string): Date => new Date(value.replace(' ', 'T'));

const isoDate = (date: Date): string => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const formatMonthDay = (date: Date): string => `${monthNames[date.getMonth()]} ${String(date.getDate()).padStart(2, '0')}`;

const formatHour = (hour: number): string => `${String(hour).padStart(2, '0')}:00`;

const dominantFocusLevel = (counts: Record<FocusLevel, number>): FocusLevel => (
  (Object.entries(counts) as [FocusLevel, number][])
    .sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'low_focus'
);

export const bucketWindowsByScope = (
  rows: WindowCluster[],
  scope: PatternScope,
): PatternBucket[] => {
  const monthBase = scope === 'month' && rows.length > 0
    ? parseTimestamp(rows[0].window_start)
    : null;
  if (monthBase) monthBase.setHours(0, 0, 0, 0);

  const buckets = new Map<string, {
    label: string;
    rangeLabel: string;
    totalWindows: number;
    totalFocusScore: number;
    totalAnomalyScore: number;
    anomalyCount: number;
    counts: Record<FocusLevel, number>;
    workRatio: number;
    learnRatio: number;
    communicationRatio: number;
    start: string;
    end: string;
  }>();

  for (const row of rows) {
    const startDate = parseTimestamp(row.window_start);
    let key = '';
    let label = '';
    let rangeLabel = '';

    if (scope === 'day') {
      const hour = startDate.getHours();
      key = `${hour}`;
      label = formatHour(hour);
      rangeLabel = `${formatHour(hour)} - ${String(hour).padStart(2, '0')}:59`;
    } else if (scope === 'week') {
      key = isoDate(startDate);
      label = weekdayNames[startDate.getDay()];
      rangeLabel = formatMonthDay(startDate);
    } else {
      const dayOffset = monthBase
        ? Math.floor((startDate.getTime() - monthBase.getTime()) / (1000 * 60 * 60 * 24))
        : 0;
      key = `week-${Math.floor(dayOffset / 7) + 1}`;
    }

    if (!buckets.has(key)) {
      buckets.set(key, {
        label,
        rangeLabel,
        totalWindows: 0,
        totalFocusScore: 0,
        totalAnomalyScore: 0,
        anomalyCount: 0,
        counts: createCounts(),
        workRatio: 0,
        learnRatio: 0,
        communicationRatio: 0,
        start: row.window_start,
        end: row.window_end,
      });
    }

    const bucket = buckets.get(key)!;
    bucket.totalWindows += 1;
    bucket.totalFocusScore += row.avg_focus_score;
    bucket.counts[row.focus_level] += 1;
    bucket.workRatio += row.work_ratio;
    bucket.learnRatio += row.learn_ratio;
    bucket.communicationRatio += row.communication_ratio;
    if (row.anomaly_score !== null) {
      bucket.totalAnomalyScore += row.anomaly_score;
      bucket.anomalyCount += 1;
    }
    if (row.window_start < bucket.start) bucket.start = row.window_start;
    if (row.window_end > bucket.end) bucket.end = row.window_end;
  }

  const sorted = [...buckets.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([key, bucket], index) => {
      if (scope === 'month') {
        const startDate = parseTimestamp(bucket.start);
        const endDate = parseTimestamp(bucket.end);
        bucket.label = `Week ${index + 1}`;
        bucket.rangeLabel = `${formatMonthDay(startDate)} - ${formatMonthDay(endDate)}`;
      }

      return {
        id: key,
        label: bucket.label,
        rangeLabel: bucket.rangeLabel,
        focusLevel: dominantFocusLevel(bucket.counts),
        avgFocusScore: bucket.totalWindows > 0 ? bucket.totalFocusScore / bucket.totalWindows : 0,
        anomalyScore: bucket.anomalyCount > 0 ? bucket.totalAnomalyScore / bucket.anomalyCount : null,
        totalWindows: bucket.totalWindows,
        counts: bucket.counts,
        workRatio: bucket.totalWindows > 0 ? bucket.workRatio / bucket.totalWindows : 0,
        learnRatio: bucket.totalWindows > 0 ? bucket.learnRatio / bucket.totalWindows : 0,
        communicationRatio: bucket.totalWindows > 0 ? bucket.communicationRatio / bucket.totalWindows : 0,
        start: bucket.start,
        end: bucket.end,
      };
    });

  return sorted;
};

export const buildFocusTrend = (
  rows: WindowCluster[],
  scope: PatternScope,
  bucket: PatternBucket | null,
): FocusTrendPoint[] => {
  if (!bucket) return [];

  const bucketRows = rows.filter(row => row.window_start >= bucket.start && row.window_end <= bucket.end);
  if (scope === 'week') {
    return bucketRows.map(row => ({
      label: row.window_start.slice(11, 16),
      focusScore: Number((row.avg_focus_score * 100).toFixed(1)),
    }));
  }

  if (scope === 'day') {
    const hourly = new Map<string, { total: number; count: number }>();
    for (const row of bucketRows) {
      const key = row.window_start.slice(11, 13) + ':00';
      const current = hourly.get(key) ?? { total: 0, count: 0 };
      current.total += row.avg_focus_score;
      current.count += 1;
      hourly.set(key, current);
    }
    return [...hourly.entries()].map(([label, value]) => ({
      label,
      focusScore: Number(((value.total / value.count) * 100).toFixed(1)),
    }));
  }

  return [];
};

export const describeBucketUnit = (scope: PatternScope): string => {
  if (scope === 'day') return 'hour';
  if (scope === 'week') return 'day';
  return 'week';
};

export const describeRangeLabel = (scope: PatternScope): string => {
  if (scope === 'day') return 'hour-by-hour';
  if (scope === 'week') return 'day-by-day';
  return 'week-by-week';
};
