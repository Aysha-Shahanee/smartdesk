import axios from 'axios';

// Base URL from environment or fallback
const BASE_URL = import.meta.env.VITE_BACKEND_URL;

if (!BASE_URL) {
  throw new Error('VITE_BACKEND_URL must be configured for the SmartDesk frontend');
}

const api = axios.create({
  baseURL: BASE_URL,
});

/**
 * Get segments summary for a given date (YYYY-MM-DD) or today.
 */
export const getSegmentsSummary = async (date?: string) => {
  const params: { date?: string; user_id?: string } = { user_id: 'local_user' };
  if (date) {
    params.date = date;
  }
  const { data } = await api.get('/dashboard/segments/summary', { params });
  return data;
};

/**
 * Get segments list for a given date with pagination.
 */
export const getSegmentsList = async (date?: string, limit = 100, offset = 0) => {
  const params: any = { user_id: 'local_user', limit, offset };
  if (date) {
    params.date = date;
  }
  const { data } = await api.get('/dashboard/segments', { params });
  return data;
};

/**
 * Record a correction for a segment.
 */
export const recordCorrection = async (segmentId: string, correctLabel: string) => {
  const { data } = await api.post(
    '/dashboard/corrections',
    { segment_id: segmentId, correct_label: correctLabel },
    { params: { user_id: 'local_user' } }
  );
  return data;
};

/**
 * Get OS dashboard summary.
 */
export const getOSDashboard = async (from?: string, to?: string) => {
  const params: any = { user_id: 'local_user' };
  if (from) params.from = from;
  if (to) params.to = to;
  const { data } = await api.get('/dashboard/os', { params });
  return data;
};

/**
 * Get IDE dashboard summary.
 */
export const getIDEDashboard = async (from?: string, to?: string) => {
  const params: any = { user_id: 'local_user' };
  if (from) params.from = from;
  if (to) params.to = to;
  const { data } = await api.get('/dashboard/ide', { params });
  return data;
};

/**
 * Get Browser dashboard summary.
 */
export const getBrowserDashboard = async (from?: string, to?: string) => {
  const params: any = { user_id: 'local_user' };
  if (from) params.from = from;
  if (to) params.to = to;
  const { data } = await api.get('/dashboard/browser', { params });
  return data;
};
