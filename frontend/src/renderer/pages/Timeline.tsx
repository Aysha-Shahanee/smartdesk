import { useEffect, useState, useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend, LabelList,
} from 'recharts';
import {
  getAllSegments, getCalendarEvents, getIDEDashboard, getOSDashboard, dayBounds,
} from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { useTheme } from '../contexts/ThemeContext';
import { getCategoryColor, getChartChrome } from '../theme/chartTheme';
import { ChangeLabelTable } from '../components/ChangeLabelTable';
import {
  capitalize, formatDuration, formatSegmentTime, formatEventTime, parseSegmentTime,
  todayString,
} from '../utils/time';
import './Timeline.css';

const SUB_TABS = ['IDE', 'Browser', 'OS / Apps', 'Calendar'] as const;
type SubTab = typeof SUB_TABS[number];

/* Timeline View is drawn against a fixed 24-hour day rather than against the
   extent of whatever happened to be recorded, so a block's horizontal position
   reads as a clock time and two days are directly comparable. */
const DAY_MS = 24 * 60 * 60 * 1000;
const GRID_HOURS = Array.from({ length: 25 }, (_, h) => h);
const AXIS_HOURS = [0, 3, 6, 9, 12, 15, 18, 21, 24];

type SummaryTile = { label: string; value: string; sub?: string };

const TAB_ICONS: Record<SubTab, string> = {
  IDE: '💻', Browser: '🌐', 'OS / Apps': '⌨️', Calendar: '📅',
};

/**
 * Which segments belong to a tab.
 *
 * This used to substring-match `app_name` against a hardcoded keyword list.
 * That list matched 4 of 562 browser segments (Comet, Acrobat, VLC, Explorer
 * and friends are absent from it) while wrongly claiming 736 non-IDE segments
 * as IDE because "Code" appears in unrelated window titles. The API now
 * returns each segment's real provenance, so the tab filters on that.
 *
 * `primary_source` alone, not `has_ide_session`/`has_browser_session`: those
 * two mean "a session of this kind overlapped in time", which is not the same
 * as "this is what the user was doing". An editor open behind a browser sets
 * `has_ide_session` on the browsing segment, so including it put 716 s of one
 * day's browser, VLC and WhatsApp time on the IDE tab. `primary_source` is
 * decided from foreground overlap and answers the question the tab asks.
 */
const TAB_FILTER: Record<Exclude<SubTab, 'Calendar'>, (seg: any) => boolean> = {
  IDE: (s) => s.primary_source === 'ide',
  Browser: (s) => s.primary_source === 'browser',
  'OS / Apps': () => true,
};

const Timeline: React.FC = () => {
  const { selectedDate: date, refreshCount } = useDateContext();
  const { theme } = useTheme();
  const chrome = getChartChrome(theme);

  const [allSegments, setAllSegments] = useState<any[]>([]);
  const [calendarEvents, setCalendarEvents] = useState<any[]>([]);
  const [idePanel, setIdePanel] = useState<any>(null);
  const [osPanel, setOsPanel] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  /* Deep link support: the Dashboard's cards point at a specific source, so
     they pass the tab through router state rather than dropping the user on
     the IDE tab and making them find it. */
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<SubTab>(() => {
    const requested = (location.state as { tab?: SubTab } | null)?.tab;
    return requested && SUB_TABS.includes(requested) ? requested : 'IDE';
  });
  const [showIdle, setShowIdle] = useState(false);

  /* All source panels are scoped to the single selected date. The previous
     Day/Week/Month toggle only ever widened the *calendar* query — segments
     were always fetched for one day — so the wider periods silently showed
     day-scoped numbers under a week/month heading. The toggle is removed
     rather than left lying about its scope. */
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const { from, to } = dayBounds(date);
      const [segs, cal, ide, os] = await Promise.all([
        getAllSegments(date).catch(() => []),
        getCalendarEvents(from, to).catch(() => null),
        getIDEDashboard(from, to).catch(() => null),
        getOSDashboard(from, to).catch(() => null),
      ]);
      if (cancelled) return;
      setAllSegments(segs);
      setCalendarEvents(cal?.events || []);
      setIdePanel(ide);
      setOsPanel(os);
      setLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, [date, refreshCount]);

  /* Idle and gap segments are excluded by default so these views agree with
     the Dashboard, whose summary endpoint counts `state = 'active'` only.
     Previously the OS tab counted idle time as activity. */
  const visibleSegments = useMemo(() => {
    if (activeTab === 'Calendar') return [];
    const base = allSegments.filter(TAB_FILTER[activeTab]);
    return showIdle ? base : base.filter(s => (s.state ?? 'active') === 'active');
  }, [allSegments, activeTab, showIdle]);

  const idleCount = useMemo(() => {
    if (activeTab === 'Calendar') return 0;
    return allSegments.filter(TAB_FILTER[activeTab]).filter(s => s.state === 'idle').length;
  }, [allSegments, activeTab]);

  /* The source/state fields were added to /dashboard/segments alongside this
     view. If the running backend predates that change every segment arrives
     without them, and the IDE and Browser tabs would silently render empty —
     say so instead of showing a blank page that looks like "no activity". */
  const backendOutdated = useMemo(
    () => allSegments.length > 0 && allSegments.every(s => s.primary_source === undefined),
    [allSegments]
  );

  const segDuration = (seg: any) => {
    if (typeof seg.duration_sec === 'number') return seg.duration_sec;
    const s = parseSegmentTime(seg.start_time_utc);
    const e = parseSegmentTime(seg.end_time_utc);
    return s && e ? Math.max(0, (e.getTime() - s.getTime()) / 1000) : 0;
  };

  /**
   * Activity per clock hour.
   *
   * Rewritten: the old version seeded a fixed 09:00–17:00 window (dropping all
   * activity outside office hours), charged a segment's whole duration to its
   * starting hour, and recomputed "idle" as `60 - active` so overlapping
   * segments produced a negative-clamped zero rather than real idle time.
   * This version derives the hour range from the data and splits each segment
   * across every hour it actually spans.
   */
  const hourlyData = useMemo(() => {
    const active = new Array(24).fill(0);
    const idle = new Array(24).fill(0);

    const accumulate = (seg: any, bucket: number[]) => {
      const start = parseSegmentTime(seg.start_time_utc);
      const end = parseSegmentTime(seg.end_time_utc);
      if (!start || !end || end <= start) return;
      let cursor = start.getTime();
      const endMs = end.getTime();
      while (cursor < endMs) {
        const c = new Date(cursor);
        const hourEnd = new Date(
          c.getFullYear(), c.getMonth(), c.getDate(), c.getHours() + 1, 0, 0, 0
        ).getTime();
        const sliceEnd = Math.min(hourEnd, endMs);
        bucket[c.getHours()] += (sliceEnd - cursor) / 60000; // minutes
        cursor = sliceEnd;
      }
    };

    const scoped = activeTab === 'Calendar' ? [] : allSegments.filter(TAB_FILTER[activeTab]);
    scoped.forEach(seg => {
      if ((seg.state ?? 'active') === 'active') accumulate(seg, active);
      else if (seg.state === 'idle') accumulate(seg, idle);
    });

    const touched = active.map((v, i) => v > 0 || idle[i] > 0 ? i : -1).filter(i => i >= 0);
    if (touched.length === 0) return [];
    const first = Math.min(...touched);
    const last = Math.max(...touched);

    const rows = [];
    for (let h = first; h <= last; h++) {
      rows.push({
        hour: `${String(h).padStart(2, '0')}:00`,
        Active: Math.round(active[h]),
        Idle: Math.round(idle[h]),
      });
    }
    return rows;
  }, [allSegments, activeTab]);

  /* Distribution is weighted by time, not by segment count. Counting segments
     made a 5-second window-focus blip rank equal to an hour of work. */
  const categoryDistribution = useMemo(() => {
    const totals: Record<string, number> = {};
    visibleSegments.forEach(seg => {
      const cat = seg.correction_label || seg.predicted_category || 'other';
      totals[cat] = (totals[cat] || 0) + segDuration(seg);
    });
    const grand = Object.values(totals).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(totals)
      // A category can accumulate segments that all round to zero seconds.
      // Charting it draws an invisible slice with a legend row reading "0s".
      .filter(([, seconds]) => seconds > 0)
      .map(([key, seconds]) => ({
        key,
        name: capitalize(key),
        value: seconds,
        percent: Math.round((seconds / grand) * 100),
        color: getCategoryColor(key, theme),
      }))
      .sort((a, b) => b.value - a.value);
  }, [visibleSegments, theme]);

  /* Time spent per domain, derived from activity segments rather than from
     `browser.top_domains`.
     browser_sessions records one row per tab, and concurrent tabs are each
     counted as foreground: on 2026-07-25 the panel reports 15.2 h of browsing
     on a day with 6.2 h of total OS activity (1.4x overlap). Activity segments
     are canonical and non-overlapping by construction, and browser segments
     carry the full URL in `detail`, so the domain split is recoverable from
     them without the double count. */
  const domainBreakdown = useMemo(() => {
    if (activeTab !== 'Browser') return [];
    const totals: Record<string, number> = {};
    visibleSegments.forEach(seg => {
      // `file://` URLs have no hostname, and some segments carry a browser
      // session link but no URL at all. Both were previously collapsed into
      // one "unknown" bucket that grew large enough to outrank real domains.
      let host: string;
      if (!seg.detail) {
        host = 'No URL recorded';
      } else {
        try {
          const u = new URL(seg.detail);
          host = u.protocol === 'file:' ? 'Local file' : (u.hostname || 'No URL recorded');
        } catch {
          host = String(seg.detail).split('/')[0] || 'No URL recorded';
        }
      }
      totals[host] = (totals[host] || 0) + segDuration(seg);
    });
    return Object.entries(totals)
      .filter(([, seconds]) => seconds > 0)
      .map(([name, seconds]) => ({ name, seconds }))
      .sort((a, b) => b.seconds - a.seconds)
      .slice(0, 10);
  }, [activeTab, visibleSegments]);

  /* Time per application, also from canonical segments. */
  const appBreakdown = useMemo(() => {
    if (activeTab !== 'OS / Apps') return [];
    const totals: Record<string, number> = {};
    visibleSegments.forEach(seg => {
      const app = seg.app_name || 'Unknown';
      totals[app] = (totals[app] || 0) + segDuration(seg);
    });
    return Object.entries(totals)
      .filter(([, seconds]) => seconds > 0)
      .map(([name, seconds]) => ({ name, seconds }))
      .sort((a, b) => b.seconds - a.seconds)
      .slice(0, 10);
  }, [activeTab, visibleSegments]);

  /* Per-tab summary tiles. Time totals come from activity segments, which are
     deduplicated and non-overlapping; the IDE panel is used for the
     counters that only ide_sessions carries (edits, saves, language,
     project) — IDE sessions were verified not to overlap, so its own
     coding-time figure is quoted directly. */
  const summaryTiles = useMemo<SummaryTile[]>(() => {
    const totalSec = visibleSegments.reduce((acc, s) => acc + segDuration(s), 0);

    if (activeTab === 'IDE') {
      const langs = idePanel?.top_languages || [];
      const projects = idePanel?.top_projects || [];
      return [
        {
          label: 'Coding Time',
          value: formatDuration(idePanel?.coding_time_sec ?? 0),
          /* The two tabs measure the editor differently and the numbers do not
             match: OS / Apps counts every second its window held focus, this
             counts only the seconds the IDE saw editor activity. Say which is
             which on the tile rather than leaving two plausible "time in VS
             Code" figures to be reconciled by guesswork. */
          sub: 'Editor active — IDE-detected idle removed',
        },
        { label: 'Top Language', value: langs[0]?.name ? capitalize(langs[0].name) : '—' },
        { label: 'Top Project', value: projects[0]?.name ?? '—' },
        { label: 'Edits / Saves', value: `${idePanel?.edits ?? 0} / ${idePanel?.saves ?? 0}` },
      ];
    }

    if (activeTab === 'Browser') {
      return [
        { label: 'Browsing Time', value: formatDuration(totalSec), sub: 'Browser window in focus' },
        { label: 'Top Domain', value: domainBreakdown[0]?.name ?? '—' },
        { label: 'Domains Visited', value: String(domainBreakdown.length) },
        { label: 'Segments', value: String(visibleSegments.length) },
      ];
    }

    const apps = new Set(visibleSegments.map(s => s.app_name).filter(Boolean));
    return [
      { label: 'Active Time', value: formatDuration(totalSec), sub: 'Window in focus, input detected' },
      { label: 'Idle Time', value: formatDuration(osPanel?.idle_time_sec ?? 0) },
      { label: 'Apps Used', value: String(apps.size) },
      { label: 'Segments', value: String(visibleSegments.length) },
    ];
  }, [activeTab, visibleSegments, idePanel, osPanel, domainBreakdown]);

  const distTitle: Record<Exclude<SubTab, 'Calendar'>, string> = {
    IDE: 'Category Distribution (IDE time)',
    Browser: 'Category Distribution (Browsing time)',
    'OS / Apps': 'Category Distribution (All activity)',
  };

  /* Top-N breakdown, each from the source that actually owns the dimension:
     languages come from ide_sessions (the only place `active_language` is
     recorded), domains and apps from canonical activity segments. */
  const breakdown = useMemo(() => {
    if (activeTab === 'IDE') {
      return {
        title: 'Time by Language',
        note: 'From IDE session records (ide_sessions.active_language), weighted by '
          + 'active coding time — these add up to the Coding Time above.',
        rows: (idePanel?.top_languages || []).map((r: any) => ({
          name: capitalize(r.name || 'unknown'),
          seconds: r.seconds,
        })),
      };
    }
    if (activeTab === 'Browser') {
      return {
        title: 'Time by Domain',
        note: 'Derived from non-overlapping activity segments, so concurrent tabs are not double-counted.',
        rows: domainBreakdown,
      };
    }
    return {
      title: 'Time by Application',
      note: 'Derived from non-overlapping activity segments. This is window-focus '
        + 'time, so an editor or browser reads higher here than on its own tab, '
        + "which also subtracts that source's own idle detection.",
      rows: appBreakdown,
    };
  }, [activeTab, idePanel, domainBreakdown, appBreakdown]);

  /**
   * Timeline View: one 00:00–24:00 track for the selected day.
   *
   * This used to pack segments into up to twelve lanes and scale the axis to
   * the first and last thing recorded. Both were misleading. The lanes read as
   * separate tracks — as if each row were a different source — when they were
   * only an overlap-avoidance device over a single non-overlapping series, and
   * the twelfth lane silently dropped everything after it. The data-fitted
   * axis gave every tab and every date its own scale, so identical-looking
   * blocks meant twenty minutes on one day and four hours on another.
   *
   * A fixed day makes position mean clock time, which is the one thing a
   * timeline is for.
   */
  const dayTimeline = useMemo(() => {
    const dayStart = new Date(`${date}T00:00:00`).getTime();
    const dayEnd = dayStart + DAY_MS;

    const blocks = visibleSegments
      .map(seg => {
        const s = parseSegmentTime(seg.start_time_utc);
        const e = parseSegmentTime(seg.end_time_utc);
        if (!s || !e) return null;
        // A segment can straddle midnight; draw only the part inside this day.
        const start = Math.max(s.getTime(), dayStart);
        const end = Math.min(Math.max(e.getTime(), s.getTime() + 1000), dayEnd);
        if (end <= start) return null;
        return { seg, start, end };
      })
      .filter(Boolean) as { seg: any; start: number; end: number }[];

    blocks.sort((a, b) => a.start - b.start);

    // Only meaningful for today: on any past date the whole track is behind us.
    const nowMs = Date.now();
    const nowPct = date === todayString() && nowMs > dayStart && nowMs < dayEnd
      ? ((nowMs - dayStart) / DAY_MS) * 100
      : null;

    return { blocks, dayStart, nowPct };
  }, [visibleSegments, date]);

  /* Calendar events for the selected day only. `getCalendarEvents` is now
     called with real day bounds; passing the bare date for both ends made the
     window a single instant at midnight, so this tab was always empty. */
  const calendarForDay = useMemo(() => {
    const events = calendarEvents.filter(e => (e.start_time || '').slice(0, 10) === date);
    const timed = events.filter(e => !e.is_all_day);
    const allDay = events.filter(e => e.is_all_day);
    const meetingSec = timed.reduce((acc, e) => acc + (e.duration_sec || 0), 0);
    return { events, timed, allDay, meetingSec };
  }, [calendarEvents, date]);

  /* Meetings laid out against the same hour grid as the activity chart, so a
     meeting block can be read against what was actually being done. */
  const calendarHourly = useMemo(() => {
    if (calendarForDay.timed.length === 0) return [];
    const perHour = new Array(24).fill(0);
    calendarForDay.timed.forEach(e => {
      const s = new Date(e.start_time);
      const en = new Date(e.end_time);
      if (Number.isNaN(s.getTime()) || Number.isNaN(en.getTime()) || en <= s) return;
      let cursor = s.getTime();
      const endMs = en.getTime();
      while (cursor < endMs) {
        const c = new Date(cursor);
        const hourEnd = new Date(c.getFullYear(), c.getMonth(), c.getDate(), c.getHours() + 1, 0, 0, 0).getTime();
        const sliceEnd = Math.min(hourEnd, endMs);
        perHour[c.getHours()] += (sliceEnd - cursor) / 60000;
        cursor = sliceEnd;
      }
    });
    const touched = perHour.map((v, i) => (v > 0 ? i : -1)).filter(i => i >= 0);
    if (touched.length === 0) return [];
    const rows = [];
    for (let h = Math.min(...touched); h <= Math.max(...touched); h++) {
      rows.push({ hour: `${String(h).padStart(2, '0')}:00`, Meetings: Math.round(perHour[h]) });
    }
    return rows;
  }, [calendarForDay]);

  if (loading) return <div className="sd-loader">Loading timeline for {date}…</div>;

  const tooltipStyle = {
    borderRadius: 8,
    border: `1px solid ${chrome.tooltipBorder}`,
    background: chrome.tooltipBg,
    color: chrome.tooltipText,
    fontSize: 13,
  };

  return (
    <div className="timeline-page sd-fade-in">
      <div className="timeline-header">
        <div>
          <h1>Activity Timeline</h1>
          <p className="subtitle">Source-based activity analysis • {date}</p>
        </div>
        {activeTab !== 'Calendar' && idleCount > 0 && (
          <div className="timeline-controls">
            <label className="idle-toggle">
              <input
                type="checkbox"
                checked={showIdle}
                onChange={e => setShowIdle(e.target.checked)}
              />
              Include idle ({idleCount})
            </label>
          </div>
        )}
      </div>

      <div className="sd-tabs">
        {SUB_TABS.map(tab => (
          <button
            key={tab}
            className={`sd-tab ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_ICONS[tab]} {tab}
          </button>
        ))}
      </div>

      {backendOutdated && (
        <div className="sd-alert sd-alert--warning" style={{ marginBottom: 'var(--space-xl)' }}>
          <span className="sd-alert-icon">⚠️</span>
          <div className="sd-alert-content">
            <h4>Restart the backend to enable source filtering</h4>
            <p>
              This build reads each segment's recorded source (<code>primary_source</code>) from
              the API, but the running backend is an older build that does not send it, so the
              IDE and Browser tabs cannot be populated. Restart the API server to pick up the
              change.
            </p>
          </div>
        </div>
      )}

      {activeTab === 'Calendar' ? (
        <div className="calendar-section">
          <div className="sd-grid-4">
            <div className="sd-card metric-card">
              <span className="metric-card-label">Meetings</span>
              <span className="metric-card-value">{calendarForDay.timed.length}</span>
              <span className="metric-card-sub">Scheduled on {date}</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Time in Meetings</span>
              <span className="metric-card-value">{formatDuration(calendarForDay.meetingSec)}</span>
              <span className="metric-card-sub">Total scheduled duration</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">All-day Events</span>
              <span className="metric-card-value">{calendarForDay.allDay.length}</span>
              <span className="metric-card-sub">Not counted in meeting time</span>
            </div>
            <div className="sd-card metric-card">
              <span className="metric-card-label">Longest Meeting</span>
              <span className="metric-card-value" style={{ fontSize: 'var(--font-size-lg)' }}>
                {calendarForDay.timed.length > 0
                  ? formatDuration(Math.max(...calendarForDay.timed.map(e => e.duration_sec || 0)))
                  : '—'}
              </span>
              <span className="metric-card-sub">Single longest block</span>
            </div>
          </div>

          {calendarHourly.length > 0 && (
            <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
              <h3>Meeting Load by Hour</h3>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={calendarHourly}>
                  <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                  <XAxis dataKey="hour" tick={{ fontSize: 12, fill: chrome.axisText }} />
                  <YAxis tick={{ fontSize: 12, fill: chrome.axisText }} unit="m" />
                  <Tooltip formatter={(v: number) => [`${v} min`, 'In meetings']} contentStyle={tooltipStyle} />
                  <Bar dataKey="Meetings" fill={getCategoryColor('meetings', theme)} radius={[3, 3, 0, 0]} maxBarSize={72} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
            <h3>Schedule for {date}</h3>
            {calendarForDay.events.length > 0 ? (
              <div className="meeting-list">
                {calendarForDay.events.map(evt => (
                  <div key={evt.event_id} className="meeting-item">
                    <span className="meeting-time">
                      {evt.is_all_day
                        ? 'All day'
                        : `${formatEventTime(evt.start_time)} – ${formatEventTime(evt.end_time)}`}
                    </span>
                    <div className="meeting-info">
                      <strong>{evt.title || 'Untitled Event'}</strong>
                      <span>
                        {evt.is_all_day
                          ? 'All-day event'
                          : `${Math.round((evt.duration_sec || 0) / 60)} minutes`}
                        {evt.is_recurring ? ' • Recurring' : ''}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="dash-empty">No calendar events on {date}.</p>
            )}
            <div className="sd-alert sd-alert--info" style={{ marginTop: 20 }}>
              <div className="sd-alert-content">
                <p>Only meeting times are tracked. No content, attendees, or descriptions are stored.</p>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="sd-card summary-card">
            <h3>Summary</h3>
            <div className="summary-grid">
              {summaryTiles.map(tile => (
                <div className="summary-stat" key={tile.label}>
                  <span className="summary-stat-label">{tile.label}</span>
                  <span className="summary-stat-value">{tile.value}</span>
                  {tile.sub && <span className="summary-stat-sub">{tile.sub}</span>}
                </div>
              ))}
            </div>
            {activeTab === 'IDE' && (
              <p className="chart-note" style={{ marginTop: 'var(--space-lg)' }}>
                Coding Time comes from the IDE extension and drops the stretches it
                saw no editor activity for. The OS / Apps tab measures the same
                editor by window focus instead, so its row for this app reads
                higher — reading, reviewing and thinking count there, not here.
              </p>
            )}
          </div>

          {visibleSegments.length === 0 ? (
            <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
              <p className="dash-empty">
                No {activeTab} activity recorded on {date}.
              </p>
            </div>
          ) : (
            <>
              <div className="sd-grid-2" style={{ marginTop: 'var(--space-xl)' }}>
                <div className="sd-card">
                  <h3>Activity by Hour</h3>
                  <ResponsiveContainer width="100%" height={250}>
                    <BarChart data={hourlyData} barGap={2}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chrome.grid} />
                      <XAxis dataKey="hour" tick={{ fontSize: 12, fill: chrome.axisText }} />
                      <YAxis tick={{ fontSize: 12, fill: chrome.axisText }} unit="m" />
                      <Tooltip formatter={(v: number, n) => [`${v} min`, n]} contentStyle={tooltipStyle} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      <Bar dataKey="Active" fill={getCategoryColor('learn', theme)} radius={[3, 3, 0, 0]} />
                      {showIdle && <Bar dataKey="Idle" fill={chrome.grid} radius={[3, 3, 0, 0]} />}
                    </BarChart>
                  </ResponsiveContainer>
                </div>

                <div className="sd-card">
                  <h3>{distTitle[activeTab]}</h3>
                  <div className="donut-container">
                    <ResponsiveContainer width="45%" height={220}>
                      <PieChart>
                        <Pie
                          data={categoryDistribution}
                          dataKey="value"
                          cx="50%"
                          cy="50%"
                          innerRadius={48}
                          outerRadius={85}
                          paddingAngle={2}
                          strokeWidth={0}
                        >
                          {categoryDistribution.map(e => <Cell key={e.key} fill={e.color} />)}
                        </Pie>
                        <Tooltip
                          formatter={(value: number, _n, entry: any) => [
                            `${formatDuration(value)} (${entry?.payload?.percent ?? 0}%)`,
                            entry?.payload?.name,
                          ]}
                          contentStyle={tooltipStyle}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="donut-legend">
                      {categoryDistribution.map(item => (
                        <div className="legend-item" key={item.key}>
                          <span className="legend-dot" style={{ background: item.color }} />
                          <span className="legend-name">{item.name}</span>
                          <span className="legend-value">{formatDuration(item.value)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {breakdown.rows.length > 0 && (
                <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                  <h3>{breakdown.title}</h3>
                  <p className="chart-note">{breakdown.note}</p>
                  <ResponsiveContainer width="100%" height={Math.max(160, breakdown.rows.length * 40)}>
                    <BarChart
                      data={breakdown.rows}
                      layout="vertical"
                      margin={{ top: 8, right: 76, bottom: 8, left: 8 }}
                    >
                      <CartesianGrid horizontal={false} stroke={chrome.grid} />
                      <XAxis
                        type="number"
                        tick={{ fontSize: 12, fill: chrome.axisText }}
                        tickFormatter={(v: number) => formatDuration(v)}
                      />
                      <YAxis
                        type="category"
                        dataKey="name"
                        width={150}
                        tick={{ fontSize: 12, fill: chrome.axisText }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip
                        cursor={{ fill: chrome.grid, fillOpacity: 0.4 }}
                        formatter={(v: number) => [formatDuration(v), 'Time']}
                        contentStyle={tooltipStyle}
                      />
                      <Bar dataKey="seconds" fill={getCategoryColor('work', theme)} radius={[0, 4, 4, 0]} maxBarSize={24}>
                        <LabelList
                          dataKey="seconds"
                          position="right"
                          formatter={(v: number) => formatDuration(v)}
                          style={{ fill: chrome.axisText, fontSize: 12 }}
                        />
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              <div className="sd-card" style={{ marginTop: 'var(--space-xl)' }}>
                <h3>Timeline View</h3>
                <p className="chart-note">
                  The full day, 00:00 to 24:00. Empty stretches are hours with no
                  recorded {activeTab} activity.
                </p>
                <div className="day-timeline">
                  <div className="day-timeline-track">
                    {GRID_HOURS.map(h => (
                      <div
                        key={h}
                        className={`day-timeline-gridline${h % 6 === 0 ? ' major' : ''}`}
                        style={{ left: `${(h / 24) * 100}%` }}
                      />
                    ))}
                    {dayTimeline.blocks.map(({ seg, start, end }) => {
                      const cat = seg.correction_label || seg.predicted_category || 'system';
                      const durMin = Math.round((end - start) / 60000);
                      return (
                        <div
                          key={seg.id}
                          className="day-timeline-segment"
                          style={{
                            left: `${((start - dayTimeline.dayStart) / DAY_MS) * 100}%`,
                            width: `${((end - start) / DAY_MS) * 100}%`,
                            backgroundColor: getCategoryColor(cat, theme),
                            opacity: seg.state === 'idle' ? 0.45 : 1,
                          }}
                          title={[
                            seg.title || seg.app_name || 'Unknown',
                            `${formatSegmentTime(seg.start_time_utc)} – ${formatSegmentTime(seg.end_time_utc)}`,
                            durMin >= 1 ? `${durMin}m` : `${Math.round((end - start) / 1000)}s`,
                            capitalize(cat),
                            seg.state === 'idle' ? '(idle)' : '',
                          ].filter(Boolean).join('\n')}
                        />
                      );
                    })}
                    {dayTimeline.nowPct !== null && (
                      <div
                        className="day-timeline-now"
                        style={{ left: `${dayTimeline.nowPct}%` }}
                        title="Now"
                      />
                    )}
                  </div>
                  <div className="day-timeline-axis">
                    {AXIS_HOURS.map(h => (
                      <span key={h} style={{ left: `${(h / 24) * 100}%` }}>
                        {String(h).padStart(2, '0')}:00
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}

      {activeTab === 'OS / Apps' && (
        <div style={{ marginTop: 'var(--space-2xl)' }}>
          <ChangeLabelTable />
        </div>
      )}
    </div>
  );
};

export default Timeline;
