import { HashRouter, Routes, Route, NavLink } from 'react-router-dom';
import Dashboard from './pages/Dashboard';
import Timeline from './pages/Timeline';
import Insights from './pages/Insights';
import Report from './pages/Report';
import Settings from './pages/Settings';
import Prediction from './pages/Prediction';
import Recommendations from './pages/Recommendations';
import './App.css';

/* ---- SVG Icon Components ---- */
const IconDashboard = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);
const IconTimeline = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
  </svg>
);
const IconInsights = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="20" x2="18" y2="10" /><line x1="12" y1="20" x2="12" y2="4" /><line x1="6" y1="20" x2="6" y2="14" />
  </svg>
);
const IconPrediction = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);
const IconReports = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><polyline points="10 9 9 9 8 9" />
  </svg>
);
const IconRecommendations = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="2" x2="12" y2="6" /><line x1="12" y1="18" x2="12" y2="22" />
    <line x1="4.93" y1="4.93" x2="7.76" y2="7.76" /><line x1="16.24" y1="16.24" x2="19.07" y2="19.07" />
    <line x1="2" y1="12" x2="6" y2="12" /><line x1="18" y1="12" x2="22" y2="12" />
    <line x1="4.93" y1="19.07" x2="7.76" y2="16.24" /><line x1="16.24" y1="7.76" x2="19.07" y2="4.93" />
  </svg>
);
const IconSettings = () => (
  <svg className="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

import { ThemeProvider, useTheme } from './contexts/ThemeContext';
import { DateProvider, useDateContext } from './contexts/DateContext';
import DatePicker from './components/DatePicker';

const ThemeToggle = () => {
  const { theme, toggleTheme } = useTheme();
  return (
    <button onClick={toggleTheme} className="sd-btn" style={{ padding: '6px', border: 'none', background: 'transparent' }} title={`Switch to ${theme === 'light' ? 'Dark' : 'Light'} Mode`}>
      {theme === 'light' ? '🌙' : '☀️'}
    </button>
  );
};

const RefreshButton = () => {
  const { triggerRefresh } = useDateContext();
  return (
    <button onClick={triggerRefresh} className="sd-btn" style={{ padding: '6px', border: 'none', background: 'transparent' }} title="Refresh Data">
      🔄
    </button>
  );
};

function AppContent() {
  return (
    <HashRouter>
      <div className="app">
        <nav className="navbar">
          <span className="navbar-brand">SmartDesk</span>
          <ul className="navbar-nav">
            <li>
              <NavLink to="/" end className={({ isActive }) => isActive ? 'active' : ''}>
                <IconDashboard /> Dashboard
              </NavLink>
            </li>
            <li>
              <NavLink to="/timeline" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconTimeline /> Timeline
              </NavLink>
            </li>
            <li>
              <NavLink to="/insights" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconInsights /> Insights
              </NavLink>
            </li>
            <li>
              <NavLink to="/prediction" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconPrediction /> Prediction
              </NavLink>
            </li>
            <li>
              <NavLink to="/report" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconReports /> Reports
              </NavLink>
            </li>
            <li>
              <NavLink to="/recommendations" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconRecommendations /> Recommendations
              </NavLink>
            </li>
            <li>
              <NavLink to="/settings" className={({ isActive }) => isActive ? 'active' : ''}>
                <IconSettings /> Settings
              </NavLink>
            </li>
          </ul>
          <div className="navbar-status" style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <DatePicker />
            <RefreshButton />
            <ThemeToggle />
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span className="status-dot"></span>
              Local
            </div>
          </div>
        </nav>
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/timeline" element={<Timeline />} />
            <Route path="/insights" element={<Insights />} />
            <Route path="/prediction" element={<Prediction />} />
            <Route path="/report" element={<Report />} />
            <Route path="/recommendations" element={<Recommendations />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}

function App() {
  return (
    <ThemeProvider>
      <DateProvider>
        <AppContent />
      </DateProvider>
    </ThemeProvider>
  );
}

export default App;