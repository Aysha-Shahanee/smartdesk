export const formatTimeSpent = (seconds) => {
  if (seconds === undefined || seconds === null) return null;
  const totalMinutes = Math.floor(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours && minutes) return `${hours} h ${minutes} min`;
  if (hours) return `${hours} h`;
  if (minutes) return `${minutes} min`;
  return '< 1 min';
};

export const formatHoursAsDuration = (hours) => {
  if (hours === undefined || hours === null || !Number.isFinite(hours) || hours < 0) return null;
  return formatTimeSpent(Math.round(hours * 3600));
};

export const getRemainingEstimateStatus = ({
  remaining_time_status: status,
  overrun_hours: overrunHours,
  approaching_initial_estimate: approaching,
}) => {
  if (status === 'estimate_exceeded') {
    const formattedOverrun = formatHoursAsDuration(overrunHours);
    return formattedOverrun
      ? `Initial estimate exceeded by ${formattedOverrun}`
      : 'Initial estimate reached';
  }
  if (status === 'completed') return 'Completed';
  if (approaching) return 'Approaching initial estimate';
  if (status === 'baseline_available') return 'Baseline available';
  return 'Remaining estimate unavailable';
};
