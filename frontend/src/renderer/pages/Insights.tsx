import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, PieChart, Pie, Cell, Legend,
  ComposedChart,
} from 'recharts';
import { useTheme } from '../contexts/ThemeContext';
import { useDateContext } from '../contexts/DateContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import {
  CurrentEmotionSession,
  EmotionStatus,
  getAllSegments,
  getCurrentEmotionSession,
  getEmotionConsent,
  getEmotionStatus,
  getStress,
  getWindowClusters,
  type StressResponse,
  startEmotionDetection,
  stopEmotionDetection,
} from '../services/api';
import { formatSegmentTime, shiftDate } from '../utils/time';
import { focusByHour, focusOutOf100, summarizeFocus, HOUR_MIN_SCORED_SEC } from '../utils/focus';
import {
  buildCategoryMix,
  buildPatternTimeline,
  buildWeeklyPatternShare,
  buildWorkRatioTrend,
  bucketWindowsByScope,
  describeBucketUnit,
  describeRangeLabel,
  type CategoryMixPoint,
  type FocusLevel,
  type PatternBucket,
  type PatternTimelinePoint,
  type PatternScope,
  type WorkRatioPoint,
  type WeeklyPatternSharePoint,
  type WindowCluster,
} from './patternDetection';
import './Insights.css';

type InsightTab = 'Focus Insights' | 'Stress Insights' | 'Pattern Detection';

/* Days behind the Focus Insights tab, ending on the selected date. */
const FOCUS_TREND_DAYS = 7;

const WORK_STATE_ORDER = ['Focused', 'Struggling', 'Disengaged', 'Fatigued', 'Overloaded'] as const;
type WorkState = typeof WORK_STATE_ORDER[number];

const WORK_STATE_COLORS: Record<WorkState, string> = {
  Focused: '#22c55e',
  Struggling: '#f59e0b',
  Disengaged: '#8b5cf6',
  Fatigued: '#ef4444',
  Overloaded: '#991b1b',
};

const FOCUS_LEVEL_LABELS: Record<FocusLevel, string> = {
  high_focus: 'High Focus',
  low_focus: 'Low Focus',
  distracted: 'Moderate Focus',
};

const PATTERN_SCOPE_LABELS: Record<PatternScope, string> = {
  day: 'Hour Analysis',
  week: 'Day Analysis',
  month: 'Week Analysis',
};

const focusLevelColor = (level: FocusLevel, theme: 'light' | 'dark') => {
  if (level === 'high_focus') return getCategoryColor('learn', theme);
  if (level === 'distracted') return getCategoryColor('documentation', theme);
  return 'var(--color-text-muted)';
};

const formatPct = (value: number) => `${Math.round(value * 100)}%`;

const getLocalIsoDate = (date = new Date()) => {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const toTimestamp = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
};

const diffMinutes = (start: string, end: string) => Math.max(0, Math.round((toTimestamp(end) - toTimestamp(start)) / 60000));

const describeAnomalyScore = (score: number | null) => {
  if (score === null) {
    return {
      label: 'Not enough data',
      note: 'No unusual-behavior signal is available for this period yet.',
    };
  }
  if (score <= -0.2) {
    return {
      label: 'Highly unusual',
      note: 'This period looks very different from your recent personal baseline.',
    };
  }
  if (score <= -0.05) {
    return {
      label: 'Slightly unusual',
      note: 'This period differs somewhat from your recent personal baseline.',
    };
  }
  return {
    label: 'Normal',
    note: 'This period is close to your recent personal baseline.',
  };
};

const findLongestStrongFocusStretch = (rows: WindowCluster[]) => {
  const sorted = [...rows].sort((a, b) => a.window_start.localeCompare(b.window_start));
  let best: { start: string; end: string; minutes: number } | null = null;
  let current: { start: string; end: string } | null = null;

  for (const row of sorted) {
    if (row.focus_level !== 'high_focus') {
      if (current) {
        const minutes = diffMinutes(current.start, current.end);
        if (!best || minutes > best.minutes) best = { ...current, minutes };
        current = null;
      }
      continue;
    }

    if (!current) {
      current = { start: row.window_start, end: row.window_end };
      continue;
    }

    if (toTimestamp(row.window_start) <= toTimestamp(current.end)) {
      current.end = row.window_end > current.end ? row.window_end : current.end;
      continue;
    }

    const minutes = diffMinutes(current.start, current.end);
    if (!best || minutes > best.minutes) best = { ...current, minutes };
    current = { start: row.window_start, end: row.window_end };
  }

  if (current) {
    const minutes = diffMinutes(current.start, current.end);
    if (!best || minutes > best.minutes) best = { ...current, minutes };
  }

  return best;
};

const recentDates = (endDate: string, days: number): string[] => {
  const anchor = new Date(`${endDate}T00:00:00`);
  const dates: string[] = [];
  for (let offset = 0; offset < days; offset += 1) {
    const current = new Date(anchor);
    current.setDate(anchor.getDate() - offset);
    dates.push(getLocalIsoDate(current));
  }
  return dates;
};

const recentCompletedDates = (endDate: string, days: number): string[] => {
  const anchor = new Date(`${endDate}T00:00:00`);
  anchor.setDate(anchor.getDate() - 1);
  const dates: string[] = [];
  for (let offset = 0; offset < days; offset += 1) {
    const current = new Date(anchor);
    current.setDate(anchor.getDate() - offset);
    dates.push(getLocalIsoDate(current));
  }
  return dates;
};

const formatShortDate = (value: string) => {
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const describeScopeSelection = (scope: PatternScope) => {
  if (scope === 'day') return 'one selected completed day from the last 30 days';
  if (scope === 'week') return 'any of the last 30 completed days';
  return 'latest monthly clustering run';
};

const describePatternView = (scope: PatternScope) => {
  if (scope === 'day') return 'Pick a day, review every hour, then open one hour to inspect pattern changes inside it.';
  if (scope === 'week') return 'Review one selected day from the last 30 completed days.';
  return 'Review one selected week and compare how high and moderate focus change from Monday to Sunday.';
};

const formatSessionTime = (value?: string | null) => {
  if (!value) return 'Not started';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatEngagementLabel = (label?: string | null) => {
  if (!label || label === 'pending') return 'Unknown';
  return label.charAt(0).toUpperCase() + label.slice(1);
};

const dominantWorkState = (scores?: Record<string, number>) => {
  if (!scores) return null;
  let dominant: WorkState | null = null;
  let highest = 0;

  WORK_STATE_ORDER.forEach(state => {
    const value = Number(scores[state] || 0);
    if (value > highest) {
      highest = value;
      dominant = state;
    }
  });

  return dominant;
};

const averageWorkStateScores = (session: CurrentEmotionSession | null) => {
  const totals = WORK_STATE_ORDER.reduce<Record<WorkState, number>>((acc, state) => {
    acc[state] = 0;
    return acc;
  }, {} as Record<WorkState, number>);

  const blocks = session?.completed_blocks || session?.blocks || [];
  blocks.forEach(block => {
    WORK_STATE_ORDER.forEach(state => {
      totals[state] += Number(block.state_scores?.[state] || 0);
    });
  });

  if (session?.current_block) {
    WORK_STATE_ORDER.forEach(state => {
      totals[state] += Number(session.current_block?.state_scores?.[state] || 0);
    });
  }

  return totals;
};

type WorkStateGridBlock = {
  block_start_time?: string;
  block_end_time?: string;
  state_scores?: Record<string, number>;
  final_state_block_count?: number;
  ready?: boolean;
};

const isCompletedReportingBlock = (block: WorkStateGridBlock) =>
  block.ready === true && Number(block.final_state_block_count || 0) >= 3;

const buildWorkStateDaySlots = (
  session: CurrentEmotionSession | null,
  selectedDate: string,
  stressPoints: WorkStateGridBlock[] = [],
) => {
  const dayStart = new Date(`${selectedDate}T00:00:00`);
  const slotMs = 15 * 60 * 1000;
  const slots = Array.from({ length: 96 }, (_, index) => {
    const slotStart = new Date(dayStart.getTime() + index * slotMs);
    const slotEnd = new Date(slotStart.getTime() + slotMs);
    return {
      index,
      label: `${slotStart.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} - ${slotEnd.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
      state: null as WorkState | null,
    };
  });

  const blocks: WorkStateGridBlock[] = [
    ...(session?.completed_blocks || session?.blocks || []),
    ...stressPoints,
  ].filter(isCompletedReportingBlock);

  blocks.forEach(block => {
    const state = dominantWorkState(block.state_scores);
    if (!state || !block.block_start_time) return;

    const start = new Date(block.block_start_time).getTime();
    const end = block.block_end_time ? new Date(block.block_end_time).getTime() : start + slotMs;
    if (Number.isNaN(start) || Number.isNaN(end)) return;

    const startIndex = Math.max(0, Math.floor((start - dayStart.getTime()) / slotMs));
    const exclusiveEnd = Math.max(start, end - 1);
    const endIndex = Math.min(95, Math.max(startIndex, Math.floor((exclusiveEnd - dayStart.getTime()) / slotMs)));
    for (let index = startIndex; index <= endIndex; index += 1) {
      slots[index].state = state;
    }
  });

  return slots;
};
const Insights: React.FC = () => {
  const { theme } = useTheme();
  const { selectedDate, refreshCount } = useDateContext();
  const chrome = getChartChrome(theme);
  const [activeTab, setActiveTab] = useState<InsightTab>('Focus Insights');
  const [emotionStatus, setEmotionStatus] = useState<EmotionStatus | null>(null);
  const [currentEmotionSession, setCurrentEmotionSession] = useState<CurrentEmotionSession | null>(null);
  const [emotionError, setEmotionError] = useState<string | null>(null);
  const [isEmotionLoading, setIsEmotionLoading] = useState(false);
  const [isStartingEmotion, setIsStartingEmotion] = useState(false);
  const [isStoppingEmotion, setIsStoppingEmotion] = useState(false);
  const [webcamConsent, setWebcamConsent] = useState<boolean | null>(null);
  const [stress, setStress] = useState<StressResponse | null>(null);

  const refreshEmotionData = useCallback(async () => {
    setIsEmotionLoading(true);
    setEmotionError(null);
    try {
      const [statusResult, sessionResult, consentResult, stressResult] = await Promise.allSettled([
        getEmotionStatus(),
        getCurrentEmotionSession(),
        getEmotionConsent(),
        getStress(selectedDate),
      ]);

      if (statusResult.status === 'fulfilled') {
        setEmotionStatus(statusResult.value);
      }
      if (sessionResult.status === 'fulfilled') {
        setCurrentEmotionSession(sessionResult.value);
      }
      if (consentResult.status === 'fulfilled') {
        setWebcamConsent(consentResult.value.webcam_enabled);
      }
      if (stressResult.status === 'fulfilled') {
        setStress(stressResult.value);
      }

      const failed = [statusResult, sessionResult, consentResult, stressResult]
        .find((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failed) {
        const reason = failed.reason;
        setEmotionError(reason instanceof Error ? reason.message : 'Emotion backend is unavailable.');
      }
    } finally {
      setIsEmotionLoading(false);
    }
  }, [selectedDate]);

  useEffect(() => {
    if (activeTab === 'Stress Insights') {
      refreshEmotionData();
    }
  }, [activeTab, refreshEmotionData]);

  useEffect(() => {
    if (activeTab !== 'Stress Insights' || !emotionStatus?.running) return;
    const intervalId = window.setInterval(refreshEmotionData, 3000);
    return () => window.clearInterval(intervalId);
  }, [activeTab, emotionStatus?.running, refreshEmotionData]);

  const handleStartEmotion = async () => {
    setIsStartingEmotion(true);
    setEmotionError(null);
    try {
      const result = await startEmotionDetection();
      setEmotionStatus(result?.status || result);
      await refreshEmotionData();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not start webcam detection.';
      setEmotionError(message);
    } finally {
      setIsStartingEmotion(false);
    }
  };

  const handleStopEmotion = async () => {
    setIsStoppingEmotion(true);
    setEmotionError(null);
    try {
      const result = await stopEmotionDetection();
      setEmotionStatus(result?.status || result);
      await refreshEmotionData();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Could not stop webcam detection.';
      setEmotionError(message);
    } finally {
      setIsStoppingEmotion(false);
    }
  };

  const workStateTotals = useMemo(
    () => averageWorkStateScores(currentEmotionSession),
    [currentEmotionSession],
  );
  const workStateTotalValue = Object.values(workStateTotals).reduce((sum, value) => sum + value, 0);
  const detectorWorkStateDistribution = WORK_STATE_ORDER.map(state => {
    const value = workStateTotals[state] || 0;
    const percent = workStateTotalValue > 0 ? Math.round((value / workStateTotalValue) * 100) : 0;

    return {
      name: state,
      value,
      percent,
      color: WORK_STATE_COLORS[state],
    };
  });
  const workStateDaySlots = useMemo(
    () => buildWorkStateDaySlots(currentEmotionSession, selectedDate, stress?.points || []),
    [currentEmotionSession, selectedDate, stress],
  );
  const workStateHours = useMemo(
    () => Array.from({ length: 24 }, (_, hour) => workStateDaySlots.slice(hour * 4, hour * 4 + 4)),
    [workStateDaySlots],
  );
  const currentEngagement = formatEngagementLabel(emotionStatus?.latest_engagement);

  const statusLabel = emotionError
    ? 'Error'
    : emotionStatus?.running
      ? 'Running'
      : emotionStatus?.session_id
        ? 'Stopped'
        : 'Not running';
  const statusBadgeClass =
    statusLabel === 'Running' ? 'sd-badge--success' :
    statusLabel === 'Error' ? 'sd-badge--danger' :
    'sd-badge--warning';
  const completedBlocks = currentEmotionSession?.completed_blocks || currentEmotionSession?.blocks || [];
  const [patternScope, setPatternScope] = useState<PatternScope>('day');
  const [patternWindows, setPatternWindows] = useState<WindowCluster[]>([]);
  const [patternLoading, setPatternLoading] = useState(false);
  const [patternError, setPatternError] = useState<string | null>(null);
  const [selectedBucketId, setSelectedBucketId] = useState<string | null>(null);
  const [selectedAnalysisDate, setSelectedAnalysisDate] = useState<string | null>(null);
  const [focusDays, setFocusDays] = useState<{ date: string; segments: any[] }[]>([]);
  const [focusLoading, setFocusLoading] = useState(false);

  /* Segments for the trailing week, loaded only while the Focus tab is open.
     This is seven paginated fetches and the other two tabs have no use for
     them, so the tab pays for its own data the way Pattern Detection does. */
  useEffect(() => {
    if (activeTab !== 'Focus Insights') return;
    let cancelled = false;

    const load = async () => {
      setFocusLoading(true);
      const dates = Array.from(
        { length: FOCUS_TREND_DAYS },
        (_, i) => shiftDate(selectedDate, -(FOCUS_TREND_DAYS - 1 - i)),
      );
      const loaded = await Promise.all(
        dates.map(date =>
          getAllSegments(date)
            .then(segments => ({ date, segments }))
            .catch(() => ({ date, segments: [] as any[] })),
        ),
      );
      if (cancelled) return;
      setFocusDays(loaded);
      setFocusLoading(false);
    };

    load();
    return () => { cancelled = true; };
  }, [activeTab, selectedDate, refreshCount]);

  /* Focus per day, duration-weighted over that day's scored segments — the same
     figure the Dashboard shows for a single date, laid out as a week. A day
     with nothing scored yields null rather than 0: an unrecorded Sunday is
     missing data, and plotting it as a zero drew a collapse in focus that never
     happened. */
  const focusTrend = useMemo(
    () => focusDays.map(({ date, segments }) => {
      const summary = summarizeFocus(segments);
      return {
        day: new Date(`${date}T00:00:00`).toLocaleDateString([], { weekday: 'short' }),
        date,
        score: summary.score === null ? null : focusOutOf100(summary.score),
        activeMin: Math.round(summary.totalSec / 60),
        coverage: summary.coverage,
      };
    }),
    [focusDays],
  );

  /* The week's best and worst hour of the day, pooled across every loaded day.
     This replaces a hardcoded "your best window is 10:00–12:00, averaging
     85/100" that no measurement stood behind. */
  const focusHighlights = useMemo(() => {
    const all = focusDays.flatMap(day => day.segments);
    const week = summarizeFocus(all);
    const hours = focusByHour(all)
      .map((score, hour) => ({ hour, score }))
      .filter((entry): entry is { hour: number; score: number } => entry.score !== null);

    if (hours.length === 0) return { week, best: null, worst: null };
    const ranked = [...hours].sort((a, b) => b.score - a.score);
    return { week, best: ranked[0], worst: ranked[ranked.length - 1] };
  }, [focusDays]);

  const hourLabel = (hour: number) =>
    `${String(hour).padStart(2, '0')}:00–${String((hour + 1) % 24).padStart(2, '0')}:00`;

  const latestAvailableAnalysisAnchor = useMemo(() => getLocalIsoDate(), []);
  const isHourAnalysis = patternScope === 'day';
  const isDayAnalysis = patternScope === 'week';
  const isMonthAnalysis = patternScope === 'month';

  const analysisDates = useMemo(
    () => recentCompletedDates(latestAvailableAnalysisAnchor, 30),
    [latestAvailableAnalysisAnchor]
  );

  useEffect(() => {
    setSelectedAnalysisDate(prev => (
      prev && analysisDates.includes(prev)
        ? prev
        : selectedDate && analysisDates.includes(selectedDate)
          ? selectedDate
          : analysisDates[0] ?? null
    ));
  }, [analysisDates, selectedDate]);

  useEffect(() => {
    if (activeTab !== 'Pattern Detection') return;
    let cancelled = false;

    const loadPatterns = async () => {
      setPatternLoading(true);
      setPatternError(null);
      try {
        const effectiveScope = isMonthAnalysis ? 'month' : 'day';
        const effectiveDate = isMonthAnalysis ? undefined : selectedAnalysisDate ?? undefined;
        const limit = isMonthAnalysis ? 5000 : 1000;
        let rows = await getWindowClusters(effectiveDate, limit, effectiveScope) as WindowCluster[];
        if (isMonthAnalysis && rows.length === 0) {
          rows = [];
        }
        if (cancelled) return;
        const sorted = [...rows].sort((a, b) => a.window_start.localeCompare(b.window_start));
        setPatternWindows(sorted);
      } catch (error) {
        if (
          isMonthAnalysis
          && error instanceof Error
          && error.message.includes('less than or equal to 1000')
        ) {
          try {
            const perDayRows = await Promise.all(
              recentDates(latestAvailableAnalysisAnchor, 35).map(date => (
                getWindowClusters(date, 500, 'month').catch(() => [])
              ))
            );
            if (cancelled) return;
            const deduped = new Map<string, WindowCluster>();
            for (const dayRows of perDayRows as WindowCluster[][]) {
              for (const row of dayRows) deduped.set(row.window_id, row);
            }
            const sorted = [...deduped.values()].sort((a, b) => a.window_start.localeCompare(b.window_start));
            setPatternWindows(sorted);
            return;
          } catch (fallbackError) {
            if (cancelled) return;
            setPatternWindows([]);
            setSelectedBucketId(null);
            setPatternError(fallbackError instanceof Error ? fallbackError.message : 'Failed to load month pattern data');
            return;
          }
        }
        if (cancelled) return;
        setPatternWindows([]);
        setSelectedBucketId(null);
        setPatternError(error instanceof Error ? error.message : 'Failed to load pattern data');
      } finally {
        if (!cancelled) setPatternLoading(false);
      }
    };

    loadPatterns();
    return () => { cancelled = true; };
  }, [activeTab, isMonthAnalysis, latestAvailableAnalysisAnchor, patternScope, refreshCount, selectedAnalysisDate]);

  const bucketScope = patternScope === 'week' ? 'day' : patternScope;

  const patternBuckets = useMemo(
    () => bucketWindowsByScope(patternWindows, bucketScope),
    [bucketScope, patternWindows]
  );

  useEffect(() => {
    setSelectedBucketId(prev => (
      prev && patternBuckets.some(bucket => bucket.id === prev)
        ? prev
        : patternBuckets[patternBuckets.length - 1]?.id ?? null
    ));
  }, [patternBuckets]);

  const selectedBucket = useMemo(
    () => patternBuckets.find(bucket => bucket.id === selectedBucketId) ?? patternBuckets[patternBuckets.length - 1] ?? null,
    [patternBuckets, selectedBucketId]
  );

  const wholeDayBucket = useMemo<PatternBucket | null>(() => {
    if (patternScope !== 'week' || patternWindows.length === 0) return null;

    const counts: Record<FocusLevel, number> = {
      high_focus: 0,
      low_focus: 0,
      distracted: 0,
    };

    let totalFocus = 0;
    let totalWork = 0;
    let totalLearn = 0;
    let totalCommunication = 0;
    let totalAnomaly = 0;
    let anomalyCount = 0;

    for (const row of patternWindows) {
      counts[row.focus_level] += 1;
      totalFocus += row.avg_focus_score;
      totalWork += row.work_ratio;
      totalLearn += row.learn_ratio;
      totalCommunication += row.communication_ratio;
      if (row.anomaly_score !== null) {
        totalAnomaly += row.anomaly_score;
        anomalyCount += 1;
      }
    }

    const focusLevel = (Object.entries(counts) as [FocusLevel, number][])
      .sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'low_focus';

    const sorted = [...patternWindows].sort((a, b) => a.window_start.localeCompare(b.window_start));
    const start = sorted[0]?.window_start ?? '';
    const end = sorted[sorted.length - 1]?.window_end ?? '';

    return {
      id: selectedAnalysisDate ?? 'selected-day',
      label: selectedAnalysisDate ? formatShortDate(selectedAnalysisDate) : 'Selected Day',
      rangeLabel: selectedAnalysisDate ?? '',
      focusLevel,
      avgFocusScore: totalFocus / patternWindows.length,
      anomalyScore: anomalyCount > 0 ? totalAnomaly / anomalyCount : null,
      totalWindows: patternWindows.length,
      counts,
      workRatio: totalWork / patternWindows.length,
      learnRatio: totalLearn / patternWindows.length,
      communicationRatio: totalCommunication / patternWindows.length,
      start,
      end,
    };
  }, [patternScope, patternWindows, selectedAnalysisDate]);

  const activeDetailBucket = patternScope === 'week' ? wholeDayBucket : selectedBucket;

  const selectedWorkTrend = useMemo<WorkRatioPoint[]>(
    () => ((isHourAnalysis || isDayAnalysis) ? buildWorkRatioTrend(patternWindows, activeDetailBucket) : []),
    [activeDetailBucket, isDayAnalysis, isHourAnalysis, patternWindows]
  );

  const selectedCategoryMix = useMemo<CategoryMixPoint[]>(
    () => ((isHourAnalysis || isDayAnalysis) ? buildCategoryMix(patternWindows, activeDetailBucket) : []),
    [activeDetailBucket, isDayAnalysis, isHourAnalysis, patternWindows]
  );

  const selectedPatternTimeline = useMemo<PatternTimelinePoint[]>(
    () => ((isHourAnalysis || isDayAnalysis) ? buildPatternTimeline(patternWindows, activeDetailBucket) : []),
    [activeDetailBucket, isDayAnalysis, isHourAnalysis, patternWindows]
  );

  const weeklyPatternShare = useMemo<WeeklyPatternSharePoint[]>(
    () => (isMonthAnalysis ? buildWeeklyPatternShare(patternWindows, selectedBucket) : []),
    [isMonthAnalysis, patternWindows, selectedBucket]
  );

  const selectedDayAnomaly = useMemo(
    () => describeAnomalyScore(activeDetailBucket?.anomalyScore ?? null),
    [activeDetailBucket]
  );

  const longestStrongFocusStretch = useMemo(
    () => (isDayAnalysis ? findLongestStrongFocusStretch(patternWindows) : null),
    [isDayAnalysis, patternWindows]
  );

  const patternSummary = useMemo(() => {
    const counts: Record<FocusLevel, number> = {
      high_focus: 0,
      low_focus: 0,
      distracted: 0,
    };

    for (const row of patternWindows) counts[row.focus_level] += 1;

    const total = patternWindows.length;
    const avgFocus = total > 0
      ? patternWindows.reduce((sum, row) => sum + row.avg_focus_score, 0) / total
      : 0;
    const unusual = [...patternWindows]
      .filter(row => row.anomaly_score !== null)
      .sort((a, b) => (a.anomaly_score ?? 0) - (b.anomaly_score ?? 0))
      .slice(0, 5);
    const unit = describeBucketUnit(bucketScope);
    const bestBucket = [...patternBuckets]
      .sort((a, b) => b.counts.high_focus - a.counts.high_focus || b.avgFocusScore - a.avgFocusScore)[0] ?? null;
    const weakestBucket = [...patternBuckets]
      .sort((a, b) => (
        (b.counts.low_focus + b.counts.distracted) - (a.counts.low_focus + a.counts.distracted)
        || a.avgFocusScore - b.avgFocusScore
      ))[0] ?? null;

    const findings: string[] = [];
    if (bestBucket) {
      findings.push(`Best focus ${unit}: ${bestBucket.label} (${bestBucket.rangeLabel}) with ${formatPct(bestBucket.avgFocusScore)} average focus.`);
    }
    if (weakestBucket) {
      findings.push(`Weakest ${unit}: ${weakestBucket.label} (${weakestBucket.rangeLabel}) with ${weakestBucket.counts.low_focus + weakestBucket.counts.distracted} lower-focus periods.`);
    }
    if (counts.distracted > 0) {
      findings.push(`${counts.distracted} moderate-focus periods were detected in this ${PATTERN_SCOPE_LABELS[patternScope].toLowerCase()} view.`);
    }
    if (total > 0) {
      findings.push(`Average focus score across analyzed periods: ${formatPct(avgFocus)}.`);
    }

    const distribution = (['high_focus', 'distracted'] as FocusLevel[])
      .map(level => ({
        key: level,
        name: FOCUS_LEVEL_LABELS[level],
        value: counts[level],
        color: focusLevelColor(level, theme),
      }))
      .filter(item => item.value > 0);

    return { counts, total, avgFocus, unusual, findings, distribution };
  }, [bucketScope, patternBuckets, patternScope, patternWindows, theme]);

  return (
    <div className="insights-page sd-fade-in">
      <div className="sd-page-header">
        <h1>Insights</h1>
        <p className="subtitle">Focus, stress and pattern analysis</p>
      </div>

      {/* Nothing on this page is placeholder any more: focus comes from segment
          focus scores, and stress is derived from recorded emotion blocks. Days
          without a detection session show an empty state rather than a made-up
          curve, so the banner has no remaining subject. */}

      <div className="sd-tabs">
        {(['Focus Insights', 'Stress Insights', 'Pattern Detection'] as InsightTab[]).map(tab => (
          <button
            key={tab}
            className={`sd-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Focus Insights' && (
        focusLoading ? (
          <div className="sd-loader">Loading the last {FOCUS_TREND_DAYS} days of focus…</div>
        ) : (
        <div className="insights-content sd-fade-in">
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Week Average</span>
              <span className="metric-card-value">
                {focusHighlights.week.score !== null
                  ? `${focusOutOf100(focusHighlights.week.score)}/100`
                  : '—'}
              </span>
              <span className="metric-card-sub">
                Across {focusHighlights.week.segments} scored segments
              </span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Best Hour</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {focusHighlights.best ? hourLabel(focusHighlights.best.hour) : '—'}
              </span>
              <span className="metric-card-sub">
                {focusHighlights.best
                  ? `${focusOutOf100(focusHighlights.best.score)}/100 pooled across the week`
                  : 'Not enough scored activity'}
              </span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Weakest Hour</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {focusHighlights.worst ? hourLabel(focusHighlights.worst.hour) : '—'}
              </span>
              <span className="metric-card-sub">
                {focusHighlights.worst
                  ? `${focusOutOf100(focusHighlights.worst.score)}/100 pooled across the week`
                  : 'Not enough scored activity'}
              </span>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Focus Score Trend (Last {FOCUS_TREND_DAYS} Days)</h3>
            <p className="pattern-description">
              Each point is that day's focus, weighted by how long each segment ran. A day with
              no scored activity has no point rather than a zero.
            </p>
            <ResponsiveContainer width="100%" height={350}>
              <LineChart data={focusTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                <XAxis dataKey="day" tick={{ fontSize: 13, fill: chrome.axisText }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 13, fill: chrome.axisText }} />
                <Tooltip
                  formatter={(value: number) => [`${value}/100`, 'Focus score']}
                  labelFormatter={(_label, payload) => payload?.[0]?.payload?.date ?? ''}
                  contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                />
                <Line
                  type="monotone"
                  dataKey="score"
                  name="Focus score"
                  stroke={getCategoryColor('work', theme)}
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: getCategoryColor('work', theme) }}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {focusHighlights.best && focusHighlights.worst && focusHighlights.week.score !== null && (
            <div className="sd-alert sd-alert--success" style={{ marginTop: 'var(--space-xl)' }}>
              <span className="sd-alert-icon">↑</span>
              <div className="sd-alert-content">
                <h4>Key Finding</h4>
                <p>
                  Your strongest hour is <strong>{hourLabel(focusHighlights.best.hour)}</strong>,
                  averaging {focusOutOf100(focusHighlights.best.score)}/100 across the last{' '}
                  {FOCUS_TREND_DAYS} days — against {focusOutOf100(focusHighlights.week.score)}/100
                  for the week overall, and {focusOutOf100(focusHighlights.worst.score)}/100 at your
                  weakest hour, {hourLabel(focusHighlights.worst.hour)}. Hours with under{' '}
                  {HOUR_MIN_SCORED_SEC / 60} minutes of scored activity are left out of this
                  comparison.
                </p>
              </div>
            </div>
          )}

          {focusHighlights.week.score === null && (
            <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
              <p className="dash-empty">
                No scored activity in the {FOCUS_TREND_DAYS} days ending {selectedDate}.
              </p>
            </div>
          )}
        </div>
        )
      )}

      {activeTab === 'Stress Insights' && (
        <div className="insights-content sd-fade-in">
          <div className="sd-card">
            <div className="stress-chart-header">
              <h3>Developer Work State Throughout the Day</h3>
              <div className="emotion-actions stress-chart-actions">
                <button
                  className="sd-btn sd-btn--primary"
                  onClick={handleStartEmotion}
                  disabled={
                    Boolean(emotionStatus?.running) ||
                    isStartingEmotion ||
                    webcamConsent === false
                  }
                  title={
                    webcamConsent === false
                      ? 'Turn on Webcam Emotion Detection in Settings first'
                      : undefined
                  }
                >
                  {isStartingEmotion ? 'Starting...' : 'Start Webcam Detection'}
                </button>
                <button
                  className="sd-btn sd-btn--danger"
                  onClick={handleStopEmotion}
                  disabled={!emotionStatus?.running || isStoppingEmotion}
                >
                  {isStoppingEmotion ? 'Stopping...' : 'Stop Webcam Detection'}
                </button>
              </div>
            </div>
            <div className="work-state-day-grid" aria-label="Developer work state throughout the selected day">
              {workStateHours.map((hourSlots, hour) => (
                <div className="work-state-hour" key={hour}>
                  <div className="work-state-hour-slots">
                    {hourSlots.map(slot => (
                      <span
                        className={`work-state-slot ${slot.state ? 'work-state-slot--filled' : ''}`}
                        key={slot.index}
                        style={{ background: slot.state ? WORK_STATE_COLORS[slot.state] : undefined }}
                        title={`${slot.label}: ${slot.state || 'No data'}`}
                      />
                    ))}
                  </div>
                  <span className="work-state-hour-label">{hour % 3 === 0 ? `${String(hour).padStart(2, '0')}:00` : ''}</span>
                </div>
              ))}
            </div>
            <div className="work-state-legend">
              {WORK_STATE_ORDER.map(state => (
                <div className="legend-item" key={state}>
                  <span className="legend-dot" style={{ background: WORK_STATE_COLORS[state] }} />
                  <span className="legend-name">{state}</span>
                </div>
              ))}
              <div className="legend-item">
                <span className="legend-dot work-state-empty-dot" />
                <span className="legend-name">No data</span>
              </div>
            </div>
          </div>

          <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
            <div className="sd-card">
              <div className="emotion-card-header">
                <h3>Work State Analysis Status</h3>
                <span className={`sd-badge ${statusBadgeClass}`}>{statusLabel}</span>
              </div>

              <div className="emotion-status-grid">
                <div>
                  <span>Session started</span>
                  <strong>{formatSessionTime(emotionStatus?.session_start_time)}</strong>
                </div>
                <div>
                  <span>Current Engagement</span>
                  <strong>{currentEngagement}</strong>
                </div>
                <div>
                  <span>Model</span>
                  <strong>{emotionStatus?.model_ready ? 'Ready' : 'Not ready'}</strong>
                </div>
                <div>
                  <span>Camera</span>
                  <strong>{emotionStatus?.camera_ready ? 'Ready' : 'Not ready'}</strong>
                </div>
              </div>

              {webcamConsent === false && !emotionError && (
                <div className="sd-alert sd-alert--warning emotion-inline-alert">
                  <span className="sd-alert-icon">🔒</span>
                  <div className="sd-alert-content">
                    <h4>Webcam detection is turned off</h4>
                    <p>
                      Turn on Webcam Emotion Detection under Settings › Privacy Controls to
                      allow SmartDesk to use your camera.
                    </p>
                  </div>
                </div>
              )}

              {emotionError && (
                <div className="sd-alert sd-alert--warning emotion-inline-alert">
                  <span className="sd-alert-icon">!</span>
                  <div className="sd-alert-content">
                    <h4>Emotion backend unavailable</h4>
                    <p>The frontend is ready, but the emotion API endpoints are not responding yet.</p>
                  </div>
                </div>
              )}

              <button className="sd-view-details emotion-refresh" onClick={refreshEmotionData} disabled={isEmotionLoading}>
                {isEmotionLoading ? 'Refreshing...' : 'Refresh emotion data'}
              </button>
            </div>

            <div className="sd-card">
              <h3>Work State Distribution – Current Session</h3>
              {workStateTotalValue > 0 ? (
                <div className="donut-container">
                  <ResponsiveContainer width="50%" height={200}>
                    <PieChart>
                      <Pie data={detectorWorkStateDistribution} dataKey="value" cx="50%" cy="50%" innerRadius={45} outerRadius={80} paddingAngle={2} strokeWidth={0}>
                        {detectorWorkStateDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
                      </Pie>
                      <Tooltip
                        formatter={(value: number, name: string) => {
                          const item = detectorWorkStateDistribution.find(state => state.name === name);
                          return [`${item?.percent || 0}%`, name];
                        }}
                        contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-legend">
                    {detectorWorkStateDistribution.map((item, i) => (
                      <div className="legend-item" key={i}>
                        <span className="legend-dot" style={{ background: item.color }} />
                        <span className="legend-name">{item.name}</span>
                        <span className="legend-value">{item.percent}%</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="dash-empty emotion-empty">
                  {emotionStatus?.running
                    ? 'Detection is running. Work state scores will appear here after the first live predictions.'
                    : completedBlocks.length === 0
                      ? 'No completed work state blocks for the current session yet.'
                      : 'No work state scores are available for this session.'}
                </div>
              )}
              <p className="chart-note">Based on live predictions and completed 15-minute blocks from the current session.</p>
            </div>
          </div>

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Privacy Controls</h3>
            <div className="privacy-list">
              <div className="privacy-item">
                <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                <div>
                  <strong>No Face Images Stored</strong>
                  <p>Only emotion labels are saved</p>
                </div>
              </div>
              <div className="privacy-item">
                <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                <div>
                  <strong>No Raw Camera Feed</strong>
                  <p>Processing happens locally</p>
                </div>
              </div>
              <div className="privacy-item">
                <span className="privacy-dot" style={{ background: 'var(--color-success)' }} />
                <div>
                  <strong>Data Stays Local First</strong>
                  <p>Only session and 15-minute block summaries are sent when backend sync is enabled</p>
                </div>
              </div>
            </div>
          </div>

          <div className="sd-alert sd-alert--warning" style={{ marginTop: 'var(--space-xl)' }}>
            <span className="sd-alert-icon">!</span>
            <div className="sd-alert-content">
              <h4>Elevated Stress After Lunch</h4>
              <p>Your stress levels increase by 40% between 1 PM - 3 PM. Consider scheduling less demanding tasks during this window.</p>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Pattern Detection' && (
        <div className="insights-content sd-fade-in">
          <div className="pattern-scope-bar">
            <div>
              <h3>Pattern Detection</h3>
              <p className="pattern-description">
                {describePatternView(patternScope)}
              </p>
            </div>
            <div className="pattern-scope-toggle">
              {(['day', 'week', 'month'] as PatternScope[]).map(scope => (
                <button
                  key={scope}
                  type="button"
                  className={`pattern-scope-button ${patternScope === scope ? 'active' : ''}`}
                  onClick={() => setPatternScope(scope)}
                >
                  {PATTERN_SCOPE_LABELS[scope]}
                </button>
              ))}
            </div>
          </div>

          {!isMonthAnalysis && analysisDates.length > 0 && (
            <div className="pattern-date-strip">
              {analysisDates.map(date => (
                <button
                  key={date}
                  type="button"
                  className={`pattern-date-chip ${selectedAnalysisDate === date ? 'active' : ''}`}
                  onClick={() => setSelectedAnalysisDate(date)}
                >
                  <span className="pattern-date-chip-title">{formatShortDate(date)}</span>
                  <span className="pattern-date-chip-sub">{date}</span>
                </button>
              ))}
            </div>
          )}

          {patternLoading ? (
            <div className="sd-loader">Loading {PATTERN_SCOPE_LABELS[patternScope].toLowerCase()} pattern data…</div>
          ) : patternError ? (
            <div className="sd-alert sd-alert--danger">
              <span className="sd-alert-icon">!</span>
              <div className="sd-alert-content">
                <h4>Pattern data could not be loaded</h4>
                <p>{patternError}</p>
              </div>
            </div>
          ) : patternSummary.total === 0 ? (
            <div className="sd-card">
              <h3>Pattern Detection</h3>
              <p className="pattern-description">
                No clustered periods are available for this {selectedAnalysisDate ?? PATTERN_SCOPE_LABELS[patternScope]} view yet. Run pattern analysis and refresh to see focus patterns here.
              </p>
            </div>
          ) : (
            <>
              <div className="sd-grid-2 pattern-overview-grid">
                <div className="pattern-stat-card">
                  <span className="pattern-stat-value" style={{ color: focusLevelColor('high_focus', theme) }}>
                    {patternSummary.counts.high_focus}
                  </span>
                  <span className="pattern-stat-label">High Focus Periods</span>
                  <span className="pattern-stat-sub">{isDayAnalysis ? 'Strong focus on this day' : isHourAnalysis ? 'Strong focus across the selected date' : 'Strong focus in this scope'}</span>
                </div>
                <div className="pattern-stat-card">
                  <span className="pattern-stat-value" style={{ color: focusLevelColor('distracted', theme) }}>
                    {patternSummary.counts.distracted}
                  </span>
                  <span className="pattern-stat-label">Moderate Focus Periods</span>
                  <span className="pattern-stat-sub">{isDayAnalysis ? 'Some focus on this day' : isHourAnalysis ? 'Some focus across the selected date' : 'Some focus, lighter consistency'}</span>
                </div>
              </div>

              {!isDayAnalysis && (
              <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                <h3>
                  {isHourAnalysis
                    ? `Hour Analysis${selectedAnalysisDate ? ` | ${selectedAnalysisDate}` : ''}`
                    : 'Week Analysis'}
                </h3>
                <p className="pattern-description">
                  {isHourAnalysis
                    ? 'Select one hour from the chosen day to inspect the dominant pattern, focus score, and category mix inside that hour.'
                    : `Select a ${describeBucketUnit(bucketScope)} to inspect the dominant pattern, focus score, and work mix for that period.`}
                </p>
                <div className="pattern-period-grid">
                  {patternBuckets.map((bucket: PatternBucket) => (
                    <button
                      key={bucket.id}
                      type="button"
                      className={`pattern-period-card ${selectedBucket?.id === bucket.id ? 'active' : ''}`}
                      onClick={() => setSelectedBucketId(bucket.id)}
                    >
                      <span
                        className="pattern-period-accent"
                        style={{ background: focusLevelColor(bucket.focusLevel, theme) }}
                      />
                      <span className="pattern-period-label">{bucket.label}</span>
                      <span className="pattern-period-range">{bucket.rangeLabel}</span>
                      <span className="pattern-period-meta">
                        {bucket.totalWindows} periods | {formatPct(bucket.avgFocusScore)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              )}

              {isMonthAnalysis && selectedBucket && (
                <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                  <h3>Weekly Focus Pattern Share</h3>
                  <p className="pattern-description">
                    Percentage of high and moderate focus periods for each day in the selected week.
                  </p>
                  <ResponsiveContainer width="100%" height={320}>
                    <BarChart data={weeklyPatternShare} barGap={6}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                      <XAxis dataKey="day" tick={{ fontSize: 12, fill: chrome.axisText }} />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fontSize: 12, fill: chrome.axisText }}
                        label={{ value: 'Share %', angle: -90, position: 'insideLeft', fill: chrome.axisText }}
                      />
                      <Tooltip
                        formatter={(value: number, name: string) => [
                          `${value}%`,
                          name === 'highFocus' ? 'High Focus' : 'Moderate Focus',
                        ]}
                        contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                      />
                      <Bar
                        dataKey="highFocus"
                        stackId="focusShare"
                        fill={focusLevelColor('high_focus', theme)}
                        radius={[4, 4, 0, 0]}
                        name="highFocus"
                      />
                      <Bar
                        dataKey="moderateFocus"
                        stackId="focusShare"
                        fill={focusLevelColor('distracted', theme)}
                        radius={[4, 4, 0, 0]}
                        name="moderateFocus"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {isDayAnalysis && activeDetailBucket && (
                <>
                  <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                    <div className="sd-card">
                      <h3>Longest Strong Focus Stretch</h3>
                      {longestStrongFocusStretch ? (
                        <>
                          <p style={{ fontSize: '1.2rem', fontWeight: 700, color: focusLevelColor('high_focus', theme), marginBottom: '0.5rem' }}>
                            {formatSegmentTime(longestStrongFocusStretch.start)} - {formatSegmentTime(longestStrongFocusStretch.end)}
                          </p>
                          <p className="pattern-description">
                            {longestStrongFocusStretch.minutes} minutes of continuous high focus on this day.
                          </p>
                        </>
                      ) : (
                        <p className="pattern-description">
                          No strong-focus stretch was detected for this day yet.
                        </p>
                      )}
                    </div>
                    <div className="sd-card">
                      <h3>Behavior Interpretation</h3>
                      <p style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '0.5rem' }}>
                        {selectedDayAnomaly.label}
                      </p>
                      <p className="pattern-description">{selectedDayAnomaly.note}</p>
                    </div>
                  </div>

                  <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                    <h3>Behavior Pattern Timeline</h3>
                    <p className="pattern-description">
                      This chart shows how behavior changed across the selected day.
                    </p>
                    {selectedPatternTimeline.length > 0 ? (
                      <>
                        <div className="pattern-timeline-legend">
                          {(['high_focus', 'distracted', 'low_focus'] as FocusLevel[]).map(level => (
                            <div className="pattern-timeline-legend-item" key={level}>
                              <span
                                className="pattern-timeline-swatch"
                                style={{ background: focusLevelColor(level, theme) }}
                              />
                              <span>{FOCUS_LEVEL_LABELS[level]}</span>
                            </div>
                          ))}
                        </div>
                        <ResponsiveContainer width="100%" height={320}>
                          <ComposedChart data={selectedPatternTimeline}>
                            <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                            <XAxis dataKey="label" tick={{ fontSize: 12, fill: chrome.axisText }} />
                            <YAxis
                              yAxisId="focus"
                              domain={[0, 100]}
                              tick={{ fontSize: 12, fill: chrome.axisText }}
                              label={{ value: 'Focus %', angle: -90, position: 'insideLeft', fill: chrome.axisText }}
                            />
                            <YAxis yAxisId="pattern" domain={[0, 20]} hide />
                            <Tooltip
                              formatter={(value: number, name: string, entry: { payload?: PatternTimelinePoint }) => {
                                const payload = entry.payload;
                                if (name === 'focusScore') return [`${value}%`, 'Focus score'];
                                if (name === 'patternBand') return [payload ? FOCUS_LEVEL_LABELS[payload.focusLevel] : value, 'Pattern'];
                                return [value, name];
                              }}
                              labelFormatter={(label, payload) => {
                                const point = payload?.[0]?.payload as PatternTimelinePoint | undefined;
                                if (!point) return `${label}`;
                                return `${label} • ${FOCUS_LEVEL_LABELS[point.focusLevel]}`;
                              }}
                              contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                            />
                            <Bar
                              yAxisId="pattern"
                              dataKey="patternBand"
                              radius={[6, 6, 0, 0]}
                              barSize={18}
                            >
                              {selectedPatternTimeline.map(point => (
                                <Cell key={`${point.label}-${point.focusLevel}`} fill={focusLevelColor(point.focusLevel, theme)} />
                              ))}
                            </Bar>
                            <Line
                              yAxisId="focus"
                              type="monotone"
                              dataKey="focusScore"
                              name="focusScore"
                              stroke={getCategoryColor('work', theme)}
                              strokeWidth={2.5}
                              dot={{ r: 3, fill: getCategoryColor('work', theme) }}
                              activeDot={{ r: 5 }}
                            />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </>
                    ) : (
                      <p className="pattern-empty-state">No detailed pattern changes are available for this day yet.</p>
                    )}
                  </div>

                  <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                  <div className="sd-card">
                    <div className="pattern-selected-cluster">
                      <span className="pattern-detail-label">Dominant Cluster for This Day</span>
                      <strong style={{ color: focusLevelColor(activeDetailBucket.focusLevel, theme) }}>
                        {FOCUS_LEVEL_LABELS[activeDetailBucket.focusLevel]}
                      </strong>
                      <p className="pattern-description">
                        {activeDetailBucket.label} ({activeDetailBucket.rangeLabel}). This is the most common pattern for the day, not the only one.
                      </p>
                    </div>
                    <h3>Work Ratio vs Time</h3>
                    <p className="pattern-description">
                      How work-oriented activity changed through the selected day.
                    </p>
                    {selectedWorkTrend.length > 0 ? (
                      <ResponsiveContainer width="100%" height={280}>
                        <LineChart data={selectedWorkTrend}>
                          <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                          <XAxis dataKey="label" tick={{ fontSize: 12, fill: chrome.axisText }} />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: chrome.axisText }} />
                          <Tooltip
                            formatter={(value: number) => [`${value}%`, 'Work ratio']}
                            contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                          />
                          <Line
                            type="monotone"
                            dataKey="workRatio"
                            stroke={getCategoryColor('work', theme)}
                            strokeWidth={2.5}
                            dot={false}
                            activeDot={{ r: 4 }}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    ) : (
                      <p className="pattern-empty-state">No detailed time breakdown is available for this day yet.</p>
                    )}
                  </div>

                  <div className="sd-card">
                    <h3>Category Mix for This Day</h3>
                    <p className="pattern-description">
                      Average time split across activity categories for the selected day.
                    </p>
                    {selectedCategoryMix.length > 0 ? (
                      <div className="donut-container pattern-day-mix">
                        <ResponsiveContainer width="50%" height={240}>
                          <PieChart>
                            <Pie
                              data={selectedCategoryMix}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              innerRadius={48}
                              outerRadius={82}
                              paddingAngle={2}
                              strokeWidth={0}
                            >
                              {selectedCategoryMix.map(item => (
                                <Cell
                                  key={item.name}
                                  fill={
                                    item.name === 'Work'
                                      ? getCategoryColor('work', theme)
                                      : item.name === 'Learning'
                                        ? getCategoryColor('learn', theme)
                                        : item.name === 'Communication'
                                          ? getCategoryColor('communication', theme)
                                          : getCategoryColor('documentation', theme)
                                  }
                                />
                              ))}
                            </Pie>
                            <Tooltip
                              formatter={(value: number) => [`${value}%`, 'Category share']}
                              contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="donut-legend">
                          {selectedCategoryMix.map(item => (
                            <div className="legend-item" key={item.name}>
                              <span
                                className="legend-dot"
                                style={{
                                  background:
                                    item.name === 'Work'
                                      ? getCategoryColor('work', theme)
                                      : item.name === 'Learning'
                                        ? getCategoryColor('learn', theme)
                                        : item.name === 'Communication'
                                          ? getCategoryColor('communication', theme)
                                          : getCategoryColor('documentation', theme),
                                }}
                              />
                              <span className="legend-name">{item.name}</span>
                              <span className="legend-value">{item.value}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="pattern-empty-state">No category mix is available for this day yet.</p>
                    )}
                  </div>
                  </div>
                </>
              )}

              {isHourAnalysis && selectedBucket && (
                <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                  <div className="sd-card">
                    <div className="pattern-selected-cluster">
                      <span className="pattern-detail-label">Dominant Cluster for This Hour</span>
                      <strong style={{ color: focusLevelColor(selectedBucket.focusLevel, theme) }}>
                        {FOCUS_LEVEL_LABELS[selectedBucket.focusLevel]}
                      </strong>
                      <p className="pattern-description">
                        {selectedBucket.rangeLabel} on {selectedAnalysisDate}. This hour averaged {formatPct(selectedBucket.avgFocusScore)} focus.
                      </p>
                    </div>
                    <h3>Pattern Changes in This Hour</h3>
                    <p className="pattern-description">
                      Pattern color and focus score through the selected hour.
                    </p>
                    {selectedPatternTimeline.length > 0 ? (
                      <ResponsiveContainer width="100%" height={320}>
                        <ComposedChart data={selectedPatternTimeline}>
                          <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                          <XAxis dataKey="label" tick={{ fontSize: 12, fill: chrome.axisText }} />
                          <YAxis
                            yAxisId="focus"
                            domain={[0, 100]}
                            tick={{ fontSize: 12, fill: chrome.axisText }}
                            label={{ value: 'Focus %', angle: -90, position: 'insideLeft', fill: chrome.axisText }}
                          />
                          <YAxis yAxisId="pattern" domain={[0, 20]} hide />
                          <Tooltip
                            formatter={(value: number, name: string, entry: { payload?: PatternTimelinePoint }) => {
                              const payload = entry.payload;
                              if (name === 'focusScore') return [`${value}%`, 'Focus score'];
                              if (name === 'patternBand') return [payload ? FOCUS_LEVEL_LABELS[payload.focusLevel] : value, 'Pattern'];
                              return [value, name];
                            }}
                            labelFormatter={(label, payload) => {
                              const point = payload?.[0]?.payload as PatternTimelinePoint | undefined;
                              if (!point) return `${label}`;
                              return `${label} • ${FOCUS_LEVEL_LABELS[point.focusLevel]}`;
                            }}
                            contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                          />
                          <Bar
                            yAxisId="pattern"
                            dataKey="patternBand"
                            radius={[6, 6, 0, 0]}
                            barSize={18}
                          >
                            {selectedPatternTimeline.map(point => (
                              <Cell key={`${point.label}-${point.focusLevel}`} fill={focusLevelColor(point.focusLevel, theme)} />
                            ))}
                          </Bar>
                          <Line
                            yAxisId="focus"
                            type="monotone"
                            dataKey="focusScore"
                            name="focusScore"
                            stroke={getCategoryColor('work', theme)}
                            strokeWidth={2.5}
                            dot={{ r: 3, fill: getCategoryColor('work', theme) }}
                            activeDot={{ r: 5 }}
                          />
                        </ComposedChart>
                      </ResponsiveContainer>
                    ) : (
                      <p className="pattern-empty-state">No detailed pattern changes are available for this hour yet.</p>
                    )}
                  </div>

                  <div className="sd-card">
                    <h3>Category Mix for This Hour</h3>
                    <p className="pattern-description">
                      Average category split across the selected hour.
                    </p>
                    {selectedCategoryMix.length > 0 ? (
                      <div className="donut-container pattern-day-mix">
                        <ResponsiveContainer width="50%" height={240}>
                          <PieChart>
                            <Pie
                              data={selectedCategoryMix}
                              dataKey="value"
                              nameKey="name"
                              cx="50%"
                              cy="50%"
                              innerRadius={48}
                              outerRadius={82}
                              paddingAngle={2}
                              strokeWidth={0}
                            >
                              {selectedCategoryMix.map(item => (
                                <Cell
                                  key={item.name}
                                  fill={
                                    item.name === 'Work'
                                      ? getCategoryColor('work', theme)
                                      : item.name === 'Learning'
                                        ? getCategoryColor('learn', theme)
                                        : item.name === 'Communication'
                                          ? getCategoryColor('communication', theme)
                                          : getCategoryColor('documentation', theme)
                                  }
                                />
                              ))}
                            </Pie>
                            <Tooltip
                              formatter={(value: number) => [`${value}%`, 'Category share']}
                              contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="donut-legend">
                          {selectedCategoryMix.map(item => (
                            <div className="legend-item" key={item.name}>
                              <span
                                className="legend-dot"
                                style={{
                                  background:
                                    item.name === 'Work'
                                      ? getCategoryColor('work', theme)
                                      : item.name === 'Learning'
                                        ? getCategoryColor('learn', theme)
                                        : item.name === 'Communication'
                                          ? getCategoryColor('communication', theme)
                                          : getCategoryColor('documentation', theme),
                                }}
                              />
                              <span className="legend-name">{item.name}</span>
                              <span className="legend-value">{item.value}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : (
                      <p className="pattern-empty-state">No category mix is available for this hour yet.</p>
                    )}
                  </div>
                </div>
              )}

              <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                <div className="sd-card">
                  <h3>Pattern Findings</h3>
                  <div className="patterns-list">
                    {patternSummary.findings.map((finding, i) => (
                      <div key={i} className="sd-alert sd-alert--success">
                        <span className="sd-alert-icon">→</span>
                        <div className="sd-alert-content">
                          <p>{finding}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="sd-card">
                  <h3>Pattern Distribution</h3>
                  <p className="pattern-description">
                    Average focus across this {isMonthAnalysis ? 'week analysis scope' : isDayAnalysis ? 'selected day' : 'selected hour view'} is {formatPct(patternSummary.avgFocus)}.
                  </p>
                  <div className="donut-container">
                    <ResponsiveContainer width="45%" height={220}>
                      <PieChart>
                        <Pie
                          data={patternSummary.distribution}
                          dataKey="value"
                          cx="50%"
                          cy="50%"
                          innerRadius={48}
                          outerRadius={82}
                          paddingAngle={2}
                          strokeWidth={0}
                        >
                          {patternSummary.distribution.map(item => (
                            <Cell key={item.key} fill={item.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          formatter={(value: number, _name, entry: { payload?: { name?: string } }) => {
                            const pct = patternSummary.total > 0
                              ? Math.round((value / patternSummary.total) * 100)
                              : 0;
                            return [`${value} periods (${pct}%)`, entry?.payload?.name ?? ''];
                          }}
                          contentStyle={{ borderRadius: 8, border: `1px solid ${chrome.tooltipBorder}`, background: chrome.tooltipBg, color: chrome.tooltipText }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="donut-legend">
                      {patternSummary.distribution.map(item => (
                        <div className="legend-item" key={item.key}>
                          <span className="legend-dot" style={{ background: item.color }} />
                          <span className="legend-name">{item.name}</span>
                          <span className="legend-value">{item.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
};

export default Insights;


