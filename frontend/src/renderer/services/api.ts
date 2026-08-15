import { fetchJson } from './fetchUtils';

const API_BASE = import.meta.env.VITE_BACKEND_URL;

if (!API_BASE) {
  throw new Error('VITE_BACKEND_URL must be configured for the SmartDesk frontend');
}

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
