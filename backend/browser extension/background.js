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
let lastStartTime = null;
let lastLoggedUrl = "";
let isIdle = false;

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
                    history[i].endTime = now.toISOString();
                    break;
                }
            }
            chrome.storage.local.set({ history: history });
        });
    }

    // Log new active tab
    const logData = {
        index: Date.now(),
        startTime: now.toISOString(),
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
    lastStartTime = now;
}

function closeCurrentSession() {
    if (!currentActiveTab) return;

    const now = new Date();

    chrome.storage.local.get({ history: [] }, (data) => {
        let history = data.history;

        for (let i = history.length - 1; i >= 0; i--) {
            if (history[i].index === currentActiveTab.index && !history[i].endTime) {
                history[i].endTime = now.toISOString();
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
// Transform & send history to backend
// =============================
function sendHistoryToBackend() {
    chrome.storage.local.get("history", (data) => {
        const history = data.history || [];
        if (history.length === 0) return;

        // Transform each entry 
        const historyPayload = history.map(e => ({
            index: e.index,
            timestamp: e.startTime,
            endTime: e.endTime,
            title: e.title || "No Title",
            url: e.url || "No URL",
            category: e.category || "Unknown"
        }));

        const wrappedPayload = {
            timestamp: new Date().toISOString(),
            event_type: "browser_history_sync",
            data: { history: historyPayload }
        };

        fetch("http://127.0.0.1:8000/api/v1/browser/", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(wrappedPayload)
        })
            .then(res => {
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                return res.json();
            })
            .then(data => {
                console.log("Server Response:", data);
                // Clear the local history after a successful send so we don't upload duplicates
                chrome.storage.local.set({ history: [] });
            })
            .catch(err => console.error("Error sending history:", err));
    });
}

// Send every 5 minutes
setInterval(sendHistoryToBackend, 5 * 60 * 1000);

// =============================
// Manual trigger in console
// =============================
function sendNow() {
    sendHistoryToBackend();
    console.log("Manual send triggered");
}

// =============================
// Export History as JSON File
// =============================
function exportHistoryToJSON() {
    chrome.storage.local.get("history", (data) => {
        const history = data.history || [];
        if (history.length === 0) {
            console.log("No history found to export.");
            return;
        }

        // Convert data to a JSON string
        const jsonString = JSON.stringify(history, null, 4);

        // Convert string to a Data URI
        const dataUri = "data:application/json;charset=utf-8," + encodeURIComponent(jsonString);

        // Trigger the download
        chrome.downloads.download({
            url: dataUri,
            filename: `SmartDesk_History_${new Date().toISOString().split('T')[0]}.json`,
            saveAs: true // Set to false if you want it to save automatically
        }, (downloadId) => {
            if (chrome.runtime.lastError) {
                console.error("Export failed:", chrome.runtime.lastError.message);
            } else {
                console.log("History exported! ID:", downloadId);
            }
        });
    });
}

// Optional: Listen for a message from your Popup/Options page to trigger export
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "download_json") {
        exportHistoryToJSON();
        sendResponse({ status: "Export started" });
    }
});






/*const focusKeywords = [
    "tutorial",
    "documentation",
    "guide",
    "learn",
    "course",
    "api",
    "programming",
    "developer",
    "stack"
];

const distractKeywords = [
    "music",
    "movie",
    "gaming",
    "funny",
    "reaction",
    "entertainment",
    "reels",
    "shorts"
];

function classifyTab(url, title) {

    if (!url || !title) return "neutral";

    let text = (url + " " + title).toLowerCase();

    if (focusKeywords.some(word => text.includes(word)))
        return "focused";

    if (distractKeywords.some(word => text.includes(word)))
        return "distracted";

    return "neutral";
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {

    if (changeInfo.status === "complete") {

        let category = classifyTab(tab.url, tab.title);

        console.log("URL:", tab.url);
        console.log("Title:", tab.title);
        console.log("Category:", category);
        console.log("----------------------------");
    }

});*/
