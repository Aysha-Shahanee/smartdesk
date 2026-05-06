// =============================
// SmartDesk Background.js
// =============================

// === Keyword lists ===

// Educational signals — checked FIRST, override distracted domains
// (e.g. a YouTube tutorial is Focused, not Distracted)
const educationalKeywords = [
    "tutorial", "course", "lecture", "learn", "how to", "howto",
    "guide", "explained", "crash course", "for beginners", "programming",
    "coding", "development", "documentation", "api", "devtools", "dev tips"
];

// Developer-focused domains
const focusedDomains = [
    "github.com", "stackoverflow.com", "developer.mozilla.org",
    "w3schools.com", "coursera.org", "udemy.com", "devdocs.io",
    "medium.com", "hashnode.com", "dev.to", "leetcode.com", "freecodecamp",
    "docs.", "research", "university"
];

// Distraction-only domains (YouTube intentionally removed — handled by educational check)
const distractedDomains = [
    "facebook.com", "instagram.com", "tiktok.com",
    "netflix.com", "twitter.com", "x.com", "reddit.com",
    "9gag.com", "twitch.tv", "gaming", "movie"
];

// ─── State ───

let currentActiveTab = null;
let isIdle = false;
let isBrowserFocused = true; // Track whether browser window is in foreground
let browserLostFocusAt = null; // Timestamp when browser lost focus

const SYNC_ALARM_NAME = "smartdeskBrowserSync";
const SYNC_INTERVAL_MINUTES = 1;
const WINDOW_MS = 60 * 1000;
const SOURCE = "browser_extension";

// History size guard — high cap for AI model training data
const MAX_HISTORY_ENTRIES = 5000;

// Offline retry queue
const pendingPayloads = [];

// === Config (from chrome.storage.sync) ===

async function getConfig() {
    return new Promise((resolve) => {
        chrome.storage.sync.get({
            userId: "",
            backendUrl: "http://127.0.0.1:8000"
        }, (config) => {
            // Fallback to empty string if userId not set
            resolve(config);
        });
    });
}

// === Dynamic Timezone Helpers ===

function getTimezone() {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function toLocalISOString(date) {
    const offsetMs = -date.getTimezoneOffset() * 60 * 1000;
    const local = new Date(date.getTime() + offsetMs);
    const sign = offsetMs >= 0 ? "+" : "-";
    const absOffset = Math.abs(date.getTimezoneOffset());
    const hh = String(Math.floor(absOffset / 60)).padStart(2, "0");
    const mm = String(absOffset % 60).padStart(2, "0");
    return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

function alignToLocalMinute(ms) {
    const offsetMs = -new Date().getTimezoneOffset() * 60 * 1000;
    const shifted = ms + offsetMs;
    const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
    return aligned - offsetMs;
}

// === Browser Detection ===

function getBrowserName() {
    // chrome.runtime.getURL returns "chrome-extension://" in both Chrome and Edge
    // navigator.userAgent is always Chrome in Edge's service worker
    // Use the extension's browser API for Firefox detection:
    if (typeof browser !== "undefined") return "Firefox";
    if (navigator.userAgent.toLowerCase().includes("edg/")) return "Edge";
    return "Chrome";
}

// === Classify tab ===
function classifyTab(tab) {
    if (!tab.url) return "Neutral";
    const text = (tab.url + " " + (tab.title || "")).toLowerCase();

    // Step 1: Educational content is always Focused (even on YouTube)
    for (let word of educationalKeywords) {
        if (text.includes(word)) return "Focused";
    }

    // Step 2: Check distracted domains
    for (let word of distractedDomains) {
        if (text.includes(word)) return "Distracted";
    }

    // Step 3: Check focused developer domains
    for (let word of focusedDomains) {
        if (text.includes(word)) return "Focused";
    }

    return "Neutral";
}

// === Log tab visit ===

function logPageVisit(tab) {
    if (!tab.url) return;
    // Don't log visits when browser is in the background
    if (!isBrowserFocused) return;
    if (currentActiveTab && currentActiveTab.url === tab.url) return; // same tab, do nothing

    const now = new Date();

    // If a previous tab was active, set its endTime
    if (currentActiveTab) {
        chrome.storage.local.get({ history: [] }, (data) => {
            let history = data.history;
            // find last log of this tab without endTime
            for (let i = history.length - 1; i >= 0; i--) {
                if (history[i].index === currentActiveTab.index && !history[i].endTime) {
                    history[i].endTime = toLocalISOString(now);
                    break;
                }
            }
            chrome.storage.local.set({ history: history });
        });
    }

    // Log new active tab
    const logData = {
        index: Date.now(),
        startTime: toLocalISOString(now),
        endTime: null,
        title: tab.title || "No Title",
        url: tab.url,
        category: classifyTab(tab)
    };

    chrome.storage.local.get({ history: [] }, (data) => {
        let history = data.history;
        history.push(logData);
        chrome.storage.local.set({ history: history }, () => {
            console.table([logData]);
        });
    });

    currentActiveTab = logData;
}

function closeCurrentSession() {
    if (!currentActiveTab) return;

    const now = new Date();
    const closingTabIndex = currentActiveTab.index;

    // Clear the active tab immediately — browser is no longer actively browsing
    currentActiveTab = null;

    chrome.storage.local.get({ history: [] }, (data) => {
        let history = data.history;

        for (let i = history.length - 1; i >= 0; i--) {
            if (history[i].index === closingTabIndex && !history[i].endTime) {
                history[i].endTime = toLocalISOString(now);
                break;
            }
        }

        chrome.storage.local.set({ history: history }, () => {
            console.log("Session closed (browser/window closed)");
        });
    });
}

// =============================
// Event listeners
// =============================

// Tab loaded or updated — only log if browser is in foreground
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === "complete" && tab.active && isBrowserFocused) {
        logPageVisit(tab);
    }
});


// Tab switch — only log if browser is in foreground
chrome.tabs.onActivated.addListener((activeInfo) => {
    if (!isBrowserFocused) return;
    chrome.tabs.get(activeInfo.tabId, (tab) => {
        if (chrome.runtime.lastError || !tab) return;
        logPageVisit(tab);
    });
});

// Window focus change — CRITICAL for background detection
chrome.windows.onFocusChanged.addListener((windowId) => {
    if (windowId === chrome.windows.WINDOW_ID_NONE) {
        // User left ALL browser windows — browser is now in background
        isBrowserFocused = false;
        browserLostFocusAt = Date.now();
        closeCurrentSession();
        return;
    }
    // Browser window regained focus
    isBrowserFocused = true;
    browserLostFocusAt = null;
    chrome.tabs.query({ active: true, windowId: windowId }, (tabs) => {
        if (chrome.runtime.lastError || !tabs || tabs.length === 0) return;
        logPageVisit(tabs[0]);
    });
});

//Browser Shutdown Listener
chrome.runtime.onSuspend.addListener(() => {
    closeCurrentSession();
});

//Window Shutdown Listener
chrome.windows.onRemoved.addListener(() => {
    closeCurrentSession();
});

// =============================
// Idle Detection
// =============================
const IDLE_THRESHOLD_SECONDS = 180; // 3 minutes

chrome.idle.setDetectionInterval(IDLE_THRESHOLD_SECONDS);

chrome.idle.onStateChanged.addListener((newState) => {
    if (newState === "idle" || newState === "locked") {
        // Developer walked away — stop counting time
        console.log("[SmartDesk] User idle/locked — closing session");
        closeCurrentSession();
        currentActiveTab = null;
        isIdle = true;
    } else if (newState === "active") {
        if (!isIdle) return; // already active, nothing to do
        isIdle = false;
        console.log("[SmartDesk] User returned — resuming tracking");
        // Resume logging from the currently active tab
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (tabs.length > 0) logPageVisit(tabs[0]);
        });
    }
});

// =============================
// Helper Functions
// =============================

function safeDomain(url) {
    if (!url) return null;
    try {
        return new URL(url).hostname || null;
    } catch {
        return null;
    }
}

// =============================
// Minute Window Builder
// =============================

function buildMinuteWindowPayload(windowStartMs, windowEndMs, history, config) {
    const windowStartIso = toLocalISOString(new Date(windowStartMs));
    const windowEndIso = toLocalISOString(new Date(windowEndMs));
    const windowDurationSec = Math.floor((windowEndMs - windowStartMs) / 1000);

    let productive = 0;
    let neutral = 0;
    let distracting = 0;
    let activeTime = 0;
    let tabSwitchCount = 0;
    const domains = new Set();

    // Calculate how much of this window the browser was in the background
    let backgroundTimeSec = 0;
    if (!isBrowserFocused && browserLostFocusAt) {
        // Browser is currently in background
        const bgStartInWindow = Math.max(browserLostFocusAt, windowStartMs);
        const bgEndInWindow = windowEndMs;
        backgroundTimeSec = Math.max(0, Math.floor((bgEndInWindow - bgStartInWindow) / 1000));
    }

    let activeTab = null;
    if (currentActiveTab && currentActiveTab.url) {
        activeTab = currentActiveTab;
    } else if (history.length > 0) {
        activeTab = history[history.length - 1];
    }

    // Fix: skip first entry to avoid inflating tab switch count
    let isFirstEntry = true;
    for (const entry of history) {
        if (!entry.startTime) continue;
        const startMs = Date.parse(entry.startTime);
        if (Number.isNaN(startMs)) continue;
        // If entry has no endTime: only extend to windowEnd if browser IS focused.
        // If browser is in background, use browserLostFocusAt as the effective end.
        let effectiveEndMs;
        if (entry.endTime) {
            effectiveEndMs = Date.parse(entry.endTime);
        } else if (!isBrowserFocused && browserLostFocusAt) {
            effectiveEndMs = browserLostFocusAt;
        } else {
            effectiveEndMs = windowEndMs;
        }
        if (Number.isNaN(effectiveEndMs)) continue;

        const overlapStart = Math.max(startMs, windowStartMs);
        const overlapEnd = Math.min(effectiveEndMs, windowEndMs);
        const overlapMs = Math.max(0, overlapEnd - overlapStart);
        if (overlapMs === 0) { isFirstEntry = false; continue; }

        const overlapSec = Math.floor(overlapMs / 1000);
        activeTime += overlapSec;

        const category = entry.category || "Neutral";
        if (category === "Focused") productive += overlapSec;
        else if (category === "Distracted") distracting += overlapSec;
        else neutral += overlapSec;

        const domain = safeDomain(entry.url);
        if (domain) domains.add(domain);

        // Fix: only count tab switches after the first entry
        const entryStartMs = startMs;
        if (!isFirstEntry && entryStartMs >= windowStartMs && entryStartMs < windowEndMs) {
            tabSwitchCount += 1;
        }
        isFirstEntry = false;
    }

    // Subtract background time from active time — browser was not in foreground
    const foregroundActiveTime = Math.max(0, activeTime - backgroundTimeSec);
    const idleSec = Math.max(0, windowDurationSec - foregroundActiveTime);
    const activeDomain = activeTab ? safeDomain(activeTab.url) : null;

    return {
        user_id: config.userId || "local_user",
        window_start: windowStartIso,
        window_end: windowEndIso,
        timezone: getTimezone(),
        browser_name: getBrowserName(),
        active_tab_domain: activeDomain,
        active_tab_url: activeTab ? activeTab.url || null : null,
        active_tab_title: activeTab ? activeTab.title || null : null,
        active_tab_category: activeTab ? activeTab.category || null : null,
        browser_active_time_sec: foregroundActiveTime,
        browser_idle_time_sec: idleSec,
        productive_time_sec: productive,
        neutral_time_sec: neutral,
        distracting_time_sec: distracting,
        communication_time_sec: 0,
        tab_switch_count: tabSwitchCount,
        unique_domains_count: domains.size,
        source: SOURCE,
    };
}

function pruneHistory(history, windowEndMs) {
    // First remove old entries (completed before this window)
    const timeFiltered = history.filter((entry) => {
        if (!entry.endTime) return true;
        const endMs = Date.parse(entry.endTime);
        if (Number.isNaN(endMs)) return true;
        return endMs > windowEndMs;
    });
    // Then enforce hard cap — keep the most recent entries for AI training data
    if (timeFiltered.length > MAX_HISTORY_ENTRIES) {
        return timeFiltered.slice(timeFiltered.length - MAX_HISTORY_ENTRIES);
    }
    return timeFiltered;
}

// =============================
// Sync: Send Minute Window
// =============================

async function sendMinuteWindowToBackend() {
    const config = await getConfig();
    const now = Date.now();
    const windowEndMs = alignToLocalMinute(now);
    const windowStartMs = windowEndMs - WINDOW_MS;

    chrome.storage.local.get("history", (data) => {
        const history = data.history || [];
        const payload = buildMinuteWindowPayload(windowStartMs, windowEndMs, history, config);

        // Include any previously failed payloads
        const toSend = [...pendingPayloads, payload];
        pendingPayloads.length = 0;

        const backendUrl = config.backendUrl || "http://127.0.0.1:8000";

        // Send all payloads
        for (const p of toSend) {
            fetch(`${backendUrl}/api/v1/browser/minute-window`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(p)
            })
                .then(res => {
                    if (!res.ok) {
                        throw new Error(`HTTP ${res.status}`);
                    }
                    return res.json();
                })
                .then(() => {
                    // Only prune history after successful send of the current payload
                    if (p === payload) {
                        const pruned = pruneHistory(history, windowEndMs);
                        chrome.storage.local.set({ history: pruned });
                    }
                })
                .catch(err => {
                    console.error("[SmartDesk] Send failed, queued for retry:", err);
                    pendingPayloads.push(p); // Re-queue for next cycle
                });
        }
    });
}

function ensureSyncAlarm() {
    chrome.alarms.create(SYNC_ALARM_NAME, {
        delayInMinutes: 1,
        periodInMinutes: SYNC_INTERVAL_MINUTES
    });
}

chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === SYNC_ALARM_NAME) {
        sendMinuteWindowToBackend();
    }
});

chrome.runtime.onInstalled.addListener(() => {
    ensureSyncAlarm();
    sendMinuteWindowToBackend();
});

chrome.runtime.onStartup.addListener(() => {
    ensureSyncAlarm();
    sendMinuteWindowToBackend();
});

// Ensure alarm exists whenever the service worker wakes up.
ensureSyncAlarm();
