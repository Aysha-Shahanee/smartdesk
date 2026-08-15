import { fetchJson } from './fetchUtils';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

/* ---------------------------------------------------------- */
/* Date-window helpers                                         */
/* ---------------------------------------------------------- */

/**
 * UTC-offset suffix ("+05:30") for a given local date.
 *
 * Required, not cosmetic: the backend's `ensure_aware()` stamps any *naive*
 * timestamp it receives as UTC before converting to the app timezone. Sending
 * a bare "2026-06-14T00:00:00" therefore asks for 05:30 local, silently
 * shifting every day window by the zone offset and dropping early events.
 */
const offsetSuffix = (date: string): string => {
  const mins = -new Date(`${date}T00:00:00`).getTimezoneOffset();
  const sign = mins >= 0 ? '+' : '-';
  const abs = Math.abs(mins);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `${sign}${hh}:${mm}`;
};

const addDays = (date: string, days: number): string => {
  const d = new Date(`${date}T00:00:00`);
  d.setDate(d.getDate() + days);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${dd}`;
};

/**
 * Inclusive local-day bounds for a YYYY-MM-DD date.
 *
 * The panel and calendar endpoints filter on `start >= from AND start <= to`.
 * Passing the bare date for both ends made `to` equal midnight, collapsing the
 * window to a single instant so it matched nothing — the Calendar tab was
 * always empty as a result.
 */
export const dayBounds = (date: string) => ({
  from: `${date}T00:00:00${offsetSuffix(date)}`,
  to: `${date}T23:59:59${offsetSuffix(date)}`,
});

/** Bounds spanning `days` calendar days starting at `date` (inclusive). */
export const rangeBounds = (date: string, days: number) => {
  const end = addDays(date, days - 1);
  return {
    from: `${date}T00:00:00${offsetSuffix(date)}`,
    to: `${end}T23:59:59${offsetSuffix(end)}`,
  };
};

/* ---------------------------------------------------------- */
/* Activity Segments — the BASE TRUTH for all views           */
/* ---------------------------------------------------------- */

/** Get aggregated summary of activity segments for a date */
export const getSegmentsSummary = async (date?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (date) queryParams.append('date', date);
  return fetchJson(`${API_BASE}/dashboard/segments/summary?${queryParams.toString()}`);
};

/** Get one page of activity segments for a date */
export const getSegmentsList = async (date?: string, limit = 500, offset = 0) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  queryParams.append('limit', limit.toString());
  queryParams.append('offset', offset.toString());
  if (date) queryParams.append('date', date);
  return fetchJson(`${API_BASE}/dashboard/segments?${queryParams.toString()}`);
};

/**
 * Every activity segment for a date, following pagination to the end.
 *
 * The endpoint caps `limit` at 500 and busy days exceed that (2026-07-25 has
 * 700), so a single request silently drops the oldest rows and every total
 * derived from it reads low.
 */
export const getAllSegments = async (date: string): Promise<any[]> => {
  const PAGE = 500;
  const first = await getSegmentsList(date, PAGE, 0);
  const total: number = first?.total ?? 0;
  const segments: any[] = [...(first?.segments || [])];

  const pages: Promise<any>[] = [];
  for (let offset = PAGE; offset < total; offset += PAGE) {
    pages.push(getSegmentsList(date, PAGE, offset));
  }
  for (const page of await Promise.all(pages)) {
    segments.push(...(page?.segments || []));
  }
  return segments;
};

/** Record a label correction for a segment */
export const recordCorrection = async (segmentId: string, correctLabel: string) => {
  return fetchJson(`${API_BASE}/dashboard/corrections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segment_id: segmentId, correct_label: correctLabel }),
  });
};

/** Alternative label endpoint via the segment_feedback route */
export const labelSegment = async (segmentId: string, correctLabel: string) => {
  return fetchJson(`${API_BASE}/api/v1/activity-segments/${segmentId}/label`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ correct_label: correctLabel }),
  });
};

/* ---------------------------------------------------------- */
/* Dashboard panels — supplementary data for richer views     */
/* ---------------------------------------------------------- */

export const getOSDashboard = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/dashboard/os?${queryParams.toString()}`);
};

export const getIDEDashboard = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/dashboard/ide?${queryParams.toString()}`);
};

export const getBrowserDashboard = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/dashboard/browser?${queryParams.toString()}`);
};

export const getTimelineDashboard = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/dashboard/timeline?${queryParams.toString()}`);
};

export const getSessionsDashboard = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/dashboard/sessions?${queryParams.toString()}`);
};

export const getOverview = async () => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  return fetchJson(`${API_BASE}/dashboard/overview?${queryParams.toString()}`);
};

export const getCalendarEvents = async (from?: string, to?: string) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (from) queryParams.append('from', from);
  if (to) queryParams.append('to', to);
  return fetchJson(`${API_BASE}/api/v1/calendar/events?${queryParams.toString()}`);
};

/* ---------------------------------------------------------- */
/* Emotion detection                                           */
/* ---------------------------------------------------------- */

export interface EmotionStatus {
  running?: boolean;
  latest_emotion?: string | null;
  session_id?: string | null;
  session_start_time?: string | null;
  model_ready?: boolean;
  camera_ready?: boolean;
  last_error?: string | null;
}

export interface EmotionBlock {
  block_start_time?: string;
  block_end_time?: string;
  dominant_emotion?: string;
  emotion_scores?: Record<string, number>;
  processed_frame_count?: number;
}

export interface CurrentEmotionSession {
  ok?: boolean;
  status?: EmotionStatus;
  session?: Record<string, unknown> | null;
  current_block?: {
    emotion_scores?: Record<string, number>;
    processed_frame_count?: number;
  } | null;
  completed_blocks?: EmotionBlock[];
  blocks?: EmotionBlock[];
}

export const startEmotionDetection = async () => {
  return fetchJson(`${API_BASE}/api/v1/emotion/start`, { method: 'POST' });
};

export const stopEmotionDetection = async () => {
  return fetchJson(`${API_BASE}/api/v1/emotion/stop`, { method: 'POST' });
};

export const getEmotionStatus = async (): Promise<EmotionStatus> => {
  const data = await fetchJson(`${API_BASE}/api/v1/emotion/status`);
  return data?.status || data;
};

export const getCurrentEmotionSession = async (): Promise<CurrentEmotionSession> => {
  return fetchJson(`${API_BASE}/api/v1/emotion/sessions/current`);
};


/* Recommendations — rule engine output                        */
/* ---------------------------------------------------------- */

export interface Recommendation {
  id: string;
  rule_id: string;
  scope: 'live' | 'daily' | 'weekly' | 'monthly';
  section: 'immediate' | 'insight' | 'planning' | 'behaviour';
  severity: 'low' | 'medium' | 'high';
  title: string;
  why: string;
  action: string;
  action_label: string | null;
  based_on: string | null;
  score: number;
  status: string;
  generated_at: string;
  facts: Record<string, unknown>;
}

export interface RecommendationResponse {
  date: string;
  daily_date: string;
  generated_at: string;
  total: number;
  sections: Record<string, Recommendation[]>;
}

/**
 * Recommendations for a date, grouped by page section.
 *
 * The endpoint generates on read when nothing is stored yet, so the page works
 * whether or not the 60-second job has been running — which matters because
 * the app is opened after the backend has been down as often as during it.
 */
export const getRecommendations = async (
  date?: string,
  refresh = false,
): Promise<RecommendationResponse> => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (date) queryParams.append('date', date);
  if (refresh) queryParams.append('refresh', 'true');
  return fetchJson(`${API_BASE}/api/v1/recommendations?${queryParams.toString()}`);
};

/** Record Applied / Not relevant / Snoozed. This is the ranker's training set. */
export const sendRecommendationFeedback = async (
  recommendationId: string,
  action: 'applied' | 'dismissed' | 'snoozed' | 'shown',
) => {
  return fetchJson(`${API_BASE}/api/v1/recommendations/${recommendationId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
};

export interface ReportMetric {
  key: string;
  label: string;
  value: number;
  unit: 'min' | 'share' | 'score' | 'count';
  baseline: number | null;
  delta: number | null;
  higher_is_better: boolean;
}

export interface ReportSection {
  key: string;
  heading: string;
  body: string[];
  items: Recommendation[] | null;
}

export interface NarrativeReport {
  scope: 'daily' | 'weekly' | 'monthly';
  period_label: string;
  period_start: string;
  period_end: string;
  generated_at: string;
  days_of_history: number;
  has_activity: boolean;
  metrics: ReportMetric[];
  categories: { name: string; minutes: number; share: number }[];
  days: { date: string; weekday: string; active_min: number; deep_min: number; focus: number }[];
  sections: ReportSection[];
}

/** Narrative report for a period. Facts are computed server-side; this is prose. */
export const getReport = async (
  scope: 'daily' | 'weekly' | 'monthly',
  date?: string,
): Promise<NarrativeReport> => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (date) queryParams.append('date', date);
  return fetchJson(`${API_BASE}/api/v1/reports/${scope}?${queryParams.toString()}`);
};

/** The same report as Markdown, for export. */
export const getReportMarkdown = async (
  scope: 'daily' | 'weekly' | 'monthly',
  date?: string,
): Promise<string> => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (date) queryParams.append('date', date);
  const res = await fetch(`${API_BASE}/api/v1/reports/${scope}/markdown?${queryParams.toString()}`);
  if (!res.ok) throw new Error(`Report export failed (${res.status})`);
  return res.text();
};

export const getWindowClusters = async (
  date?: string,
  limit = 500,
  scope: 'day' | 'week' | 'month' = 'day',
) => {
  const queryParams = new URLSearchParams();
  queryParams.append('limit', String(limit));
  queryParams.append('scope', scope);
  if (date) queryParams.append('date', date);
  return fetchJson(`${API_BASE}/api/v1/window-clusters?${queryParams.toString()}`);
};
