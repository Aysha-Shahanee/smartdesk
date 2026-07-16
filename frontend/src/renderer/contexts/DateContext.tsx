import React, { createContext, useContext, useState } from 'react';

interface DateContextType {
  selectedDate: string; // ISO date string 'YYYY-MM-DD'
  setSelectedDate: (date: string) => void;
  refreshCount: number;
  triggerRefresh: () => void;
}

const getTodayString = () => new Date().toISOString().split('T')[0];

const DateContext = createContext<DateContextType | undefined>(undefined);

export const DateProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [selectedDate, setSelectedDate] = useState<string>(getTodayString());
  const [refreshCount, setRefreshCount] = useState(0);

  const triggerRefresh = () => setRefreshCount(prev => prev + 1);

  return (
    <DateContext.Provider value={{ selectedDate, setSelectedDate, refreshCount, triggerRefresh }}>
      {children}
    </DateContext.Provider>
  );
};

export const useDateContext = () => {
  const context = useContext(DateContext);
  if (!context) {
    throw new Error('useDateContext must be used within a DateProvider');
  }
  return context;
};
