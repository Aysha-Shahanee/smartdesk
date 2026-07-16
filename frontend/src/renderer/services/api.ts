import { fetchJson } from './fetchUtils';

const API_BASE = import.meta.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000';

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

/** Get list of activity segments for a date (with pagination) */
export const getSegmentsList = async (date?: string, limit = 500, offset = 0) => {
  const queryParams = new URLSearchParams();
  queryParams.append('user_id', 'local_user');
  queryParams.append('limit', limit.toString());
  queryParams.append('offset', offset.toString());
  if (date) queryParams.append('date', date);
  return fetchJson(`${API_BASE}/dashboard/segments?${queryParams.toString()}`);
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