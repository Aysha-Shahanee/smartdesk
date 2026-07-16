import React from 'react';
import { useDateContext } from '../contexts/DateContext';

const DatePicker: React.FC = () => {
  const { selectedDate, setSelectedDate } = useDateContext();

  const handleDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSelectedDate(e.target.value);
  };

  const handlePrevDay = () => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() - 1);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  const handleNextDay = () => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + 1);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  const isToday = selectedDate === new Date().toISOString().split('T')[0];

  return (
    <div className="period-toggle" style={{ display: 'flex', alignItems: 'center', gap: '8px', border: 'none' }}>
      <button className="sd-btn" onClick={handlePrevDay} style={{ padding: '6px 10px' }}>&larr;</button>
      <input 
        type="date" 
        className="date-picker" 
        value={selectedDate} 
        onChange={handleDateChange} 
      />
      <button className="sd-btn" onClick={handleNextDay} disabled={isToday} style={{ padding: '6px 10px' }}>&rarr;</button>
    </div>
  );
};

export default DatePicker;
