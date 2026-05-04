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

// Track currently active tab
let currentActiveTab = null;
let isIdle = false;
const SYNC_ALARM_NAME = "smartdeskBrowserSync";
const SYNC_INTERVAL_MINUTES = 1;
const WINDOW_MS = 60 * 1000;
const USER_ID = "demo_user";
const SCHEMA_VERSION = "1.0";
const SOURCE = "browser_extension";
const COLOMBO_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const COLOMBO_TIMEZONE = "Asia/Colombo";

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
    if (currentActiveTab && currentActiveTab.url === tab.url) return; // same tab, do nothing

    const now = new Date();

    // If a previous tab was active, set its endTime
    if (currentActiveTab) {
        chrome.storage.local.get({ history: [] }, (data) => {
            let history = data.history;
            // find last log of this tab without endTime
            for (let i = history.length - 1; i >= 0; i--) {
                if (history[i].index === currentActiveTab.index && !history[i].endTime) {
                    history[i].endTime = toColomboISOString(now);
                    break;
                }
            }
            chrome.storage.local.set({ history: history });
        });
    }

    // Log new active tab
    const logData = {
        index: Date.now(),
        startTime: toColomboISOString(now),
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

    chrome.storage.local.get({ history: [] }, (data) => {
        let history = data.history;

        for (let i = history.length - 1; i >= 0; i--) {
            if (history[i].index === currentActiveTab.index && !history[i].endTime) {
                history[i].endTime = toColomboISOString(now);
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

// Tab loaded or updated
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (changeInfo.status === "complete" && tab.active) {
        logPageVisit(tab);
    }
});


// Tab switch
chrome.tabs.onActivated.addListener((activeInfo) => {
    chrome.tabs.get(activeInfo.tabId, (tab) => {
        if (chrome.runtime.lastError || !tab) return;
        logPageVisit(tab);
    });
});

// Window focus change
chrome.windows.onFocusChanged.addListener((windowId) => {
    // User left browser
    if (windowId === chrome.windows.WINDOW_ID_NONE) {
        closeCurrentSession();
        return;
    }
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

function getTimezone() {
    return COLOMBO_TIMEZONE;
}

function getBrowserName() {
    const ua = (navigator.userAgent || "").toLowerCase();
    if (ua.includes("edg")) return "Edge";
    if (ua.includes("firefox")) return "Firefox";
    if (ua.includes("chrome")) return "Chrome";
    if (ua.includes("safari")) return "Safari";
    return "Unknown";
}

function safeDomain(url) {
    if (!url) return null;
    try {
        return new URL(url).hostname || null;
    } catch {
        return null;
    }
}

function toColomboISOString(date) {
    const colomboDate = new Date(date.getTime() + COLOMBO_OFFSET_MS);
    const yyyy = colomboDate.getUTCFullYear();
    const mm = String(colomboDate.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(colomboDate.getUTCDate()).padStart(2, "0");
    const hh = String(colomboDate.getUTCHours()).padStart(2, "0");
    const mi = String(colomboDate.getUTCMinutes()).padStart(2, "0");
    const ss = String(colomboDate.getUTCSeconds()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}+05:30`;
}

function alignToColomboMinute(ms) {
    const shifted = ms + COLOMBO_OFFSET_MS;
    const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
    return aligned - COLOMBO_OFFSET_MS;
}

// =============================
// Minute Window Builder
// =============================

function buildMinuteWindowPayload(windowStartMs, windowEndMs, history) {
    const windowStartIso = toColomboISOString(new Date(windowStartMs));
    const windowEndIso = toColomboISOString(new Date(windowEndMs));
    const windowDurationSec = Math.floor((windowEndMs - windowStartMs) / 1000);

    let productive = 0;
    let neutral = 0;
    let distracting = 0;
    let activeTime = 0;
    let tabSwitchCount = 0;
    const domains = new Set();

    let activeTab = null;
    if (currentActiveTab && currentActiveTab.url) {
        activeTab = currentActiveTab;
    } else if (history.length > 0) {
        activeTab = history[history.length - 1];
    }

    for (const entry of history) {
        if (!entry.startTime) continue;
        const startMs = Date.parse(entry.startTime);
        if (Number.isNaN(startMs)) continue;
        const endMs = entry.endTime ? Date.parse(entry.endTime) : windowEndMs;
        if (Number.isNaN(endMs)) continue;

        const overlapStart = Math.max(startMs, windowStartMs);
        const overlapEnd = Math.min(endMs, windowEndMs);
        const overlapMs = Math.max(0, overlapEnd - overlapStart);
        if (overlapMs === 0) continue;

        const overlapSec = Math.floor(overlapMs / 1000);
        activeTime += overlapSec;

        const category = entry.category || "Neutral";
        if (category === "Focused") productive += overlapSec;
        else if (category === "Distracted") distracting += overlapSec;
        else neutral += overlapSec;

        const domain = safeDomain(entry.url);
        if (domain) domains.add(domain);

        const entryStartMs = startMs;
        if (entryStartMs >= windowStartMs && entryStartMs < windowEndMs) {
            tabSwitchCount += 1;
        }
    }

    const idleSec = Math.max(0, windowDurationSec - activeTime);
    const activeDomain = activeTab ? safeDomain(activeTab.url) : null;

    return {
        user_id: USER_ID,
        window_start: windowStartIso,
        window_end: windowEndIso,
        timezone: getTimezone(),
        browser_name: getBrowserName(),
        active_tab_domain: activeDomain,
        active_tab_url: activeTab ? activeTab.url || null : null,
        active_tab_title: activeTab ? activeTab.title || null : null,
        active_tab_category: activeTab ? activeTab.category || null : null,
        browser_active_time_sec: activeTime,
        browser_idle_time_sec: idleSec,
        productive_time_sec: productive,
        neutral_time_sec: neutral,
        distracting_time_sec: distracting,
        communication_time_sec: 0,
        tab_switch_count: tabSwitchCount,
        unique_domains_count: domains.size,
        source: SOURCE,
        schema_version: SCHEMA_VERSION,
        created_at: toColomboISOString(new Date()),
        updated_at: toColomboISOString(new Date())
    };
}

function pruneHistory(history, windowEndMs) {
    return history.filter((entry) => {
        if (!entry.endTime) return true;
        const endMs = Date.parse(entry.endTime);
        if (Number.isNaN(endMs)) return true;
        return endMs > windowEndMs;
    });
}

// =============================
// Sync: Send Minute Window
// =============================

function sendMinuteWindowToBackend() {
    const now = Date.now();
    const windowEndMs = alignToColomboMinute(now);
    const windowStartMs = windowEndMs - WINDOW_MS;

    chrome.storage.local.get("history", (data) => {
        const history = data.history || [];
        const payload = buildMinuteWindowPayload(windowStartMs, windowEndMs, history);

        fetch("http://127.0.0.1:8000/api/v1/browser/minute-window", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        })
            .then(res => {
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                return res.json();
            })
            .then(() => {
                const pruned = pruneHistory(history, windowEndMs);
                chrome.storage.local.set({ history: pruned });
            })
            .catch(err => console.error("Error sending minute window:", err));
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


