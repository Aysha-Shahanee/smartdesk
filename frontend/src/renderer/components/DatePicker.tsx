import React from 'react';
import { useDateContext } from '../contexts/DateContext';
import { shiftDate, todayString } from '../utils/time';

const DatePicker: React.FC = () => {
  const { selectedDate, setSelectedDate } = useDateContext();

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSelectedDate(e.target.value);
  };

  // Day stepping and the "is today" test both go through local-date helpers.
  // Round-tripping via toISOString() compared against the UTC date, which
  // disagrees with the selected local date before the UTC offset each night.
  const today = todayString();
  const isToday = selectedDate >= today;

  return (
    <div className="period-toggle" style={{ display: 'flex', alignItems: 'center', gap: '8px', border: 'none' }}>
      <button
        className="sd-btn"
        onClick={() => setSelectedDate(shiftDate(selectedDate, -1))}
        style={{ padding: '6px 10px' }}
        title="Previous day"
      >
        &larr;
      </button>
      <input
        type="date"
        className="date-picker"
        value={selectedDate}
        max={today}
        onChange={handleDateChange}
      />
      <button
        className="sd-btn"
        onClick={() => setSelectedDate(shiftDate(selectedDate, 1))}
        disabled={isToday}
        style={{ padding: '6px 10px' }}
        title="Next day"
      >
        &rarr;
      </button>
    </div>
  );
};

export default DatePicker;
