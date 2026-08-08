// SmartDesk Browser Extension — v2.0.0  (Manifest V3 Service Worker)
// Session-based architecture: emits "started" / "ended" / "state" events.
//
// Endpoint: POST /api/v1/ingest/browser/event
// Schema:   BrowserEventPayload (see backend/app/models/schemas/ingest.py)
//
// Events:
//   started  — user switches to a new tab / URL
//   ended    — tab is closed or URL changes away
//   state    — periodic heartbeat while tab is active (every 30s)

// ─── Configuration ────────────────────────────────────────────────────────────
const DEFAULT_CONFIG = {
  backendUrl: "http://127.0.0.1:8000",
  userId: "local_user",
  enabled: true,
  heartbeatIntervalSec: 30,
};

const INGEST_PATH = "/api/v1/ingest/browser/event";

// Minimum tab duration to emit an "ended" event (matches plan.md 3-second filter)
const MIN_SESSION_MS = 3000;

// ─── Domain helpers ───────────────────────────────────────────────────────────

function extractDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function classifyDomain(domain) {
  if (!domain) return "Neutral";
  const d = domain.toLowerCase();

  const focused = [
    "github.com", "gitlab.com", "stackoverflow.com", "docs.", "developer.",
    "npmjs.com", "pypi.org", "readthedocs.io", "devdocs.io", "mdn.", "jira.",
    "notion.so", "linear.app", "figma.com", "codepen.io", "repl.it",
  ];
  const distracted = [
    "youtube.com", "twitter.com", "x.com", "reddit.com", "instagram.com",
    "facebook.com", "tiktok.com", "netflix.com", "twitch.tv", "9gag.com",
    "buzzfeed.com",
  ];
  const communication = [
    "slack.com", "teams.microsoft.com", "discord.com", "mail.google.com",
    "outlook.live.com", "outlook.office.com", "zoom.us", "meet.google.com",
    "whereby.com", "webex.com",
  ];

  if (focused.some((k) => d.includes(k))) return "Focused";
  if (distracted.some((k) => d.includes(k))) return "Distracted";
  if (communication.some((k) => d.includes(k))) return "Communication";
  return "Neutral";
}

function getBrowserName() {
  const ua = navigator.userAgent;
  if (ua.includes("Edg/")) return "Edge";
  if (ua.includes("OPR/") || ua.includes("Opera")) return "Opera";
  if (ua.includes("Brave")) return "Brave";
  if (ua.includes("Firefox")) return "Firefox";
  if (ua.includes("Chrome")) return "Chrome";
  return "Unknown";
}

function nowIso() {
  const now = new Date();
  const offsetMin = -now.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const absOffsetMin = Math.abs(offsetMin);
  const hh = String(Math.floor(absOffsetMin / 60)).padStart(2, "0");
  const mm = String(absOffsetMin % 60).padStart(2, "0");
  const local = new Date(now.getTime() + offsetMin * 60000);

  return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

// ─── State ────────────────────────────────────────────────────────────────────

let config = { ...DEFAULT_CONFIG };
let activeSession = null;     // { tabId, windowId, url, domain, title, startMs }
let heartbeatTimer = null;

// ─── HTTP helper ──────────────────────────────────────────────────────────────

// ─── Offline retry queue ──────────────────────────────────────────────────────
const RETRY_QUEUE_MAX = 50;
const _retryQueue = [];

async function postEvent(payload) {
  if (!config.enabled) return;
  await _sendOrQueue(payload);
}

async function _sendOrQueue(payload) {
  try {
    const res = await fetch(`${config.backendUrl}${INGEST_PATH}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(5000),
    });
    // On success: flush any queued events
    if (res.ok && _retryQueue.length > 0) {
      const queued = _retryQueue.splice(0);
      for (const p of queued) await _sendOrQueue(p);
    }
  } catch {
    // Backend not reachable — queue for retry
    if (_retryQueue.length < RETRY_QUEUE_MAX) {
      _retryQueue.push(payload);
    }
  }
}

// ─── Config loader ────────────────────────────────────────────────────────────

async function loadConfig() {
  try {
    const stored = await chrome.storage.local.get([
      "backendUrl", "userId", "enabled", "heartbeatIntervalSec",
    ]);
    config = { ...DEFAULT_CONFIG, ...stored };
    if (!config.userId) {
      config.userId = "local_user";
    }
  } catch {
    config = { ...DEFAULT_CONFIG };
  }
}

// ─── Session lifecycle ────────────────────────────────────────────────────────

async function startSession(tab, trigger) {
  await endSession("navigation"); // Close any existing session first

  if (!tab?.url || tab.url.startsWith("chrome://") || tab.url.startsWith("about:")) {
    return;
  }

  const domain = extractDomain(tab.url);

  activeSession = {
    tabId: tab.id,
    windowId: tab.windowId,
    url: tab.url,
    domain,
    title: tab.title,
    startMs: Date.now(),
  };

  await postEvent({
    user_id: config.userId,
    event: "started",
    browser_name: getBrowserName(),
    timestamp: nowIso(),
    browser_window_id: tab.windowId,
    tab_id: tab.id,
    domain,
    url: tab.url,
    title: tab.title,
    category: classifyDomain(domain),
    trigger: trigger || "navigation",
  });

  scheduleHeartbeat();
}

async function endSession(trigger) {
  if (!activeSession) return;

  clearHeartbeat();

  const durationMs = Date.now() - activeSession.startMs;
  if (durationMs < MIN_SESSION_MS) {
    // Too short — skip, matches backend's 3-second filter
    activeSession = null;
    return;
  }

  await postEvent({
    user_id: config.userId,
    event: "ended",
    browser_name: getBrowserName(),
    timestamp: nowIso(),
    browser_window_id: activeSession.windowId,
    tab_id: activeSession.tabId,
    domain: activeSession.domain,
    url: activeSession.url,
    title: activeSession.title,
    category: classifyDomain(activeSession.domain),
    trigger,
  });

  activeSession = null;
}

async function sendHeartbeat() {
  if (!activeSession) return;

  // Refresh title (may have changed for SPAs)
  try {
    const tab = await chrome.tabs.get(activeSession.tabId);
    activeSession.title = tab.title;
  } catch {
    // Tab may have closed
  }

  await postEvent({
    user_id: config.userId,
    event: "state",
    browser_name: getBrowserName(),
    timestamp: nowIso(),
    browser_window_id: activeSession.windowId,
    tab_id: activeSession.tabId,
    domain: activeSession.domain,
    url: activeSession.url,
    title: activeSession.title,
    category: classifyDomain(activeSession.domain),
  });
}

// ─── Heartbeat timer ──────────────────────────────────────────────────────────

function scheduleHeartbeat() {
  clearHeartbeat();
  const intervalMs = (config.heartbeatIntervalSec || 30) * 1000;
  heartbeatTimer = setInterval(sendHeartbeat, intervalMs);
}

function clearHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

// ─── Event listeners ──────────────────────────────────────────────────────────

// Tab activated (user switched to this tab)
chrome.tabs.onActivated.addListener(async ({ tabId, windowId }) => {
  await loadConfig();
  try {
    const tab = await chrome.tabs.get(tabId);
    await startSession(tab, "tab_switch");
  } catch {
    // Tab may have been closed already
  }
});

// URL changed in the active tab
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!changeInfo.url) return;
  if (!tab.active) return;
  await loadConfig();
  await startSession(tab, "navigation");
});

// Tab closed
chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (activeSession?.tabId === tabId) {
    await endSession("tab_closed");
  }
});

// Window focus changed
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Browser lost focus
    await endSession("blur");
    return;
  }
  await loadConfig();
  try {
    const [tab] = await chrome.tabs.query({ active: true, windowId });
    if (tab) await startSession(tab, "focus");
  } catch {
    // Ignore
  }
});

// Only collect while the browser is actually the focused window — a wakeup
// or install while the browser sits in the background must not open sessions.
async function isBrowserFocused() {
  try {
    const win = await chrome.windows.getLastFocused();
    return Boolean(win && win.focused);
  } catch {
    return false;
  }
}

// Extension installed / updated → pick up the current active tab
chrome.runtime.onInstalled.addListener(async () => {
  await loadConfig();
  if (!(await isBrowserFocused())) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await startSession(tab, "install");
  } catch {
    // Ignore
  }
});

// Service worker wakeup → re-attach to current tab
(async () => {
  await loadConfig();
  if (!(await isBrowserFocused())) return;
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await startSession(tab, "wakeup");
  } catch {
    // Ignore
  }
})();
