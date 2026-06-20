# SmartDesk Project Summary

## Overview
SmartDesk is a personal productivity tracker built on a session-based architecture. It monitors OS foreground activity, IDE usage, browser activity, and calendar events, grouping them into logical work periods for dashboard reporting.

## Core Architecture
The system follows a session-based approach where:
- The OS monitor is the single source of truth for session boundaries and timestamps
- VS Code and browser extensions act as detail providers only, enriching sessions with app-specific data
- Sessions represent continuous, uninterrupted periods of activity on a specific context
- Work periods are logical blocks of work (30-minute activity blocks with no gaps)

## Key Components
1. **Backend Services** (FastAPI):
   - Session Coordinator: Manages session open/close lifecycle and PID cross-matching
   - Session Timeout Job: Closes abandoned/broken sessions (safety net)
   - Work Period Scheduler: Groups sessions into work periods
   - Dashboard Service: Aggregates data for API endpoints
   - OS Collector: Monitors foreground window changes (running as background thread)

2. **Data Collection Layer**:
   - OS Events: Foreground app/window changes, idle state
   - VS Code Events: File edits, saves, navigation
   - Browser Events: Tab switches, URL changes, site categorization
   - Calendar Events: Google Calendar synchronization

3. **Database Schema**:
   - `os_sessions`: OS foreground periods
   - `vscode_sessions`: VS Code window/file sessions
   - `browser_sessions`: Browser tab sessions
   - `calendar_events`: Google Calendar events
   - `work_periods`: 30-minute activity blocks

## Features
- Real-time activity tracking with sub-second OS polling
- Session-based organization (not time-window based)
- Offline buffering and retry mechanism in extensions
- Foreground validation via OS PID cross-checking
- 3-second minimum duration rule for browser sessions to filter distractions
- Comprehensive dashboard APIs for OS, IDE, Browser, Timeline, and Sessions views
- Extensible design supporting future AI-powered insights

## Current Status
All development phases are complete with 51/51 tests passing. The system provides:
- Fully working FastAPI backend with auto-starting background services
- Live dashboard endpoints for all panels
- Functional ingestion routes for OS, VS Code, and browser events
- Working VS Code and browser extensions (session-based)
- Legacy shim for backward compatibility
- Comprehensive test suite covering unit and integration tests

## Future Readiness
The architecture supports:
- AI coding pattern insights (via lines_added/deleted, edit_count per session)
- AI distraction detection (via browser session categorization)
- AI daily report generation (via work period logical blocks)
- Cloud migration (local tables are PostgreSQL-compatible)
- Team comparison (via user_id column on all tables)
- GitHub/Jira correlation (via hashed repo_id and git_branch)
- Notification/alerting systems (real-time distracted session detection)
- Export capabilities (CSV/PDF via existing aggregation)

## Database Location
SQLite database file: `backend/smartdesk.db`

## Access Points
- Backend API: http://127.0.0.1:8000
- API Documentation: http://127.0.0.1:8000/docs
- Health Check: http://127.0.0.1:8000/health/
- Dashboard Status: http://127.0.0.1:8000/dashboard/status