export function formatTimeSpent(seconds?: number | null): string | null;
export function formatHoursAsDuration(hours?: number | null): string | null;
export function getRemainingEstimateStatus(task: {
  remaining_time_status?: string;
  overrun_hours?: number | null;
  approaching_initial_estimate?: boolean;
}): string;
