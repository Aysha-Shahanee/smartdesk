import { fetchJson } from './fetchUtils';

/* Falls back to the local backend so a fresh clone runs without a .env, and so
   this file agrees with main.ts and preload.ts, which both default the same
   way. Set VITE_BACKEND_URL to point at a deployed backend. */
const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

export interface GitHubConnectionStatus {
  user_id: string;
  connection_status: 'connected' | 'disconnected';
  github_login?: string;
  selected_project_id?: string;
  selected_project_number?: number;
  selected_project_title?: string;
}

export interface GitHubProject {
  project_id: string;
  number: number;
  title: string;
  owner: string;
}

export interface GitHubStatusOption { id: string; name: string }

export interface GitHubActiveTask {
  project_item_id: string;
  issue_number?: number | null;
  title: string;
  repository?: string;
  logical_status: 'ACTIVE';
  started_at: string;
  predicted_typical_hours?: number;
  task_active_seconds?: number | null;
  time_spent_hours?: number | null;
  time_attribution_status?: 'repository_match' | 'branch_match' | 'no_match' | 'ambiguous';
  calculated_through?: string;
  data_status?: 'complete' | 'partial' | 'unavailable';
  remaining_time_hours?: number | null;
  remaining_time_status?:
    | 'baseline_available'
    | 'estimate_exceeded'
    | 'completed'
    | 'time_spent_unavailable'
    | 'initial_prediction_unavailable';
  overrun_hours?: number | null;
  approaching_initial_estimate?: boolean;
}

const GITHUB_API = `${API_BASE}/api/v1/integrations/github`;

export const getGitHubStatus = (): Promise<GitHubConnectionStatus> =>
  fetchJson(`${GITHUB_API}/status`);

export const beginGitHubConnection = (): Promise<{ installation_url: string }> =>
  fetchJson(`${GITHUB_API}/connect`);

export const getGitHubProjects = (): Promise<{ projects: GitHubProject[] }> =>
  fetchJson(`${GITHUB_API}/projects`);

export const selectGitHubProject = (project: GitHubProject) =>
  fetchJson(`${GITHUB_API}/project`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      owner: project.owner,
      project_number: project.number,
      project_id: project.project_id,
      title: project.title,
    }),
  });

export const getGitHubStatusOptions = (): Promise<{ options: GitHubStatusOption[] }> =>
  fetchJson(`${GITHUB_API}/status-options`);

export const getGitHubStatusMapping = (): Promise<{ mapping: Record<string, string> }> =>
  fetchJson(`${GITHUB_API}/status-mapping`);

export const saveGitHubStatusMapping = (mapping: Record<string, string>) =>
  fetchJson(`${GITHUB_API}/status-mapping`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mapping }),
  });

export const disconnectGitHub = () =>
  fetchJson(`${GITHUB_API}/connection`, { method: 'DELETE' });

export const getGitHubActiveTasks = (): Promise<{ tasks: GitHubActiveTask[] }> =>
  fetchJson(`${GITHUB_API}/active-tasks`);

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
    block_start_time?: string;
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

export interface StressPoint {
  block_start_time: string;
  block_end_time: string;
  /** 0–100. Derived from the block's emotion mix — see emotion_stress_service.py. */
  stress: number;
  /** 0–1, how much the block's frame count justifies trusting it. */
  confidence: number;
  processed_frame_count: number;
  duration_minutes: number;
  dominant_emotion: string;
}

export interface StressSummary {
  /** null when the window holds no observed blocks — render an empty state, not a zero. */
  score: number | null;
  observed_minutes: number;
  block_count: number;
  driver: string | null;
}

export interface StressResponse {
  from: string;
  to: string;
  summary: StressSummary;
  points: StressPoint[];
}

/** Stress for a local day, derived from recorded emotion blocks. */
export const getStress = async (date: string): Promise<StressResponse> => {
  const { from, to } = dayBounds(date);
  const params = new URLSearchParams({ from, to });
  return fetchJson(`${API_BASE}/api/v1/emotion/stress?${params.toString()}`);
};

export interface EmotionConsent {
  webcam_enabled: boolean;
}

/* Webcam capture is opt-in. The backend refuses /start with 403 until this is
   granted, so the toggle in Settings is the real control, not a hint. */
export const getEmotionConsent = async (): Promise<EmotionConsent> => {
  return fetchJson(`${API_BASE}/api/v1/emotion/consent`);
};

export const setEmotionConsent = async (webcamEnabled: boolean): Promise<EmotionConsent> => {
  return fetchJson(`${API_BASE}/api/v1/emotion/consent`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ webcam_enabled: webcamEnabled }),
  });
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

/* ---------------------------------------------------------- */
/* Rule health — per-rule telemetry over recorded feedback     */
/* ---------------------------------------------------------- */

/**
 * One rule's record. `verdict` compares the rule against *this user's own*
 * acceptance rate rather than a fixed bar, because acceptance in this class
 * of system varies enormously between people — a constant would measure
 * temperament rather than rule quality.
 *
 *  - `below`    the whole confidence interval sits under the user's average
 *  - `above`    the whole interval sits over it
 *  - `typical`  the interval straddles it, i.e. no evidence of a difference
 *  - `unproven` fired, but too few judged cards to rate
 *  - `silent`   never fired in the window; says nothing about quality
 */
export interface RuleHealth {
  rule_id: string;
  scope: string | null;
  section: string | null;
  severity: string | null;
  known: boolean;
  fired: number;
  applied: number;
  dismissed: number;
  snoozed: number;
  expired: number;
  still_active: number;
  judged: number;
  acceptance: number | null;
  acceptance_low: number | null;
  acceptance_high: number | null;
  ppv: number | null;
  response_rate: number | null;
  median_seconds_to_apply: number | null;
  median_seconds_to_dismiss: number | null;
  first_fired: string | null;
  last_fired: string | null;
  verdict: 'below' | 'typical' | 'unproven' | 'above' | 'silent';
  muted: boolean;
}

/** The scrutability controls and their current settings. */
export interface RecommendationPreferences {
  baseline_epoch: string | null;
  sensitivity: number;
  muted: string[];
  shadowed: string[];
}

/** One ordering strategy's offline scores. */
export interface RankingMetrics {
  strategy: string;
  k: number;
  days: number;
  precision_at_k: number | null;
  recall_at_k: number | null;
  ndcg_at_k: number | null;
  mrr: number | null;
  hit_rate: number | null;
  coverage: number | null;
  diversity: number | null;
  /**
   * Self-normalised inverse-propensity estimate of this ordering's value.
   *
   * The only figure here about a policy the user never saw: the others score
   * orderings of cards that were actually shown. Null unless exploration has
   * produced the propensity variation the estimator needs.
   */
  off_policy_value: number | null;
}

/** One rule scored against days where the condition was planted or withheld. */
export interface RuleAccuracy {
  rule_id: string;
  positives: number;
  negatives: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  gated: number;
  errors: string[];
  precision: number | null;
  recall: number | null;
  f1: number | null;
}

export interface SimulationReport {
  seed: number;
  rules: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  precision: number | null;
  recall: number | null;
  gated: number;
  errors: string[];
  per_rule: Record<string, RuleAccuracy>;
  /** Detection rate keyed by how many sigma the planted deviation was. */
  sensitivity: Record<string, Record<string, number>>;
}

export interface EvaluationReport {
  k: number;
  days_evaluated: number;
  labelled_cards: number;
  relevant_cards: number;
  beats_random: boolean | null;
  ranker_helps: boolean | null;
  strategies: Record<string, RankingMetrics>;
  support: {
    identified: boolean;
    reason: string;
    cards_with_propensity: number;
    explored_cards: number;
  };
}

export interface RuleHealthReport {
  user_id: string;
  since: string | null;
  overall_acceptance: number | null;
  overall_judged: number;
  overall_fired: number;
  muted_count: number;
  rules: RuleHealth[];
}

/** Per-rule fire rate, acceptance, PPV and time-to-action. Worst rules first. */
export const getRuleHealth = async (since?: string): Promise<RuleHealthReport> => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  if (since) queryParams.append('since', since);
  return fetchJson(`${API_BASE}/api/v1/recommendations/rules/health?${queryParams.toString()}`);
};

/**
 * Switch a rule off, or back on.
 *
 * Takes effect at generation: a muted rule stops producing cards rather than
 * having its cards hidden. Cards it produced before are kept — the record of
 * a rule doing badly is what justifies muting it.
 */
export const setRuleMuted = async (
  ruleId: string,
  muted: boolean,
): Promise<{ rule_id: string; muted: boolean }> => {
  const queryParams = new URLSearchParams({ user_id: 'local_user' });
  return fetchJson(
    `${API_BASE}/api/v1/recommendations/rules/${ruleId}/mute?${queryParams.toString()}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ muted }),
    },
  );
};

/** Run a rule silently: evaluated on real data, its output recorded, never shown. */
export const setRuleShadow = async (
  ruleId: string,
  shadow: boolean,
): Promise<{ rule_id: string; shadow: boolean }> => {
  const queryParams = new URLSearchParams({ user_id: 'local_user' });
  return fetchJson(
    `${API_BASE}/api/v1/recommendations/rules/${ruleId}/shadow?${queryParams.toString()}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shadow }),
    },
  );
};

/** The scrutability controls and their current settings. */
export const getRecommendationPreferences = async (): Promise<RecommendationPreferences> =>
  fetchJson(`${API_BASE}/api/v1/recommendations/preferences?user_id=local_user`);

/**
 * Ignore recorded activity before `date` when computing baselines.
 *
 * Nothing is deleted — the activity stays in the timeline, only the baseline
 * window moves. Passing null clears the epoch and restores every comparison.
 */
export const setBaselineEpoch = async (
  date: string | null,
): Promise<{ baseline_epoch: string | null }> =>
  fetchJson(
    `${API_BASE}/api/v1/recommendations/preferences/baseline-epoch?user_id=local_user`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date }),
    },
  );

/** How far from usual a day must be before the engine mentions it. */
export const setSensitivity = async (
  value: number,
): Promise<{ sensitivity: number }> =>
  fetchJson(
    `${API_BASE}/api/v1/recommendations/preferences/sensitivity?user_id=local_user`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    },
  );

/** Offline evaluation of the ordering against its own ablations. */
export const getEvaluation = async (k = 3): Promise<EvaluationReport> =>
  fetchJson(
    `${API_BASE}/api/v1/recommendations/evaluation?user_id=local_user&k=${k}`,
  );

/**
 * Rule accuracy against synthetic days with planted conditions.
 *
 * The only measurement here that is precision and recall in the ordinary
 * sense: the condition is put into the features on purpose, so the right
 * answer is known before the rule runs.
 */
export const getSimulation = async (seed = 0): Promise<SimulationReport> =>
  fetchJson(`${API_BASE}/api/v1/recommendations/simulation?seed=${seed}`);

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
