import type { GitHubActiveTask } from '../services/api';

export interface DashboardPredictionSummary {
  task: GitHubActiveTask;
  activeTaskCount: number;
  moreTaskCount: number;
  initialEstimate: string;
  initialEstimateDetail: string;
  timeSpent: string;
  timeSpentDetail: string;
  remainingEstimate: string;
  remainingEstimateDetail: string;
}

export function selectMostRecentlyStartedTask(tasks: GitHubActiveTask[]): GitHubActiveTask | null;
export function buildDashboardPredictionSummary(tasks: GitHubActiveTask[]): DashboardPredictionSummary | null;
