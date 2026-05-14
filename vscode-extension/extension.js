// SmartDesk VS Code Extension — v2.0.0
// Session-based architecture: emits "started" and "ended" events to the backend.
//
// Endpoint: POST /api/v1/ingest/vscode/event
// Schema:   VSCodeEventPayload (see backend/app/models/schemas/ingest.py)

const vscode = require("vscode");
const http = require("http");
const { randomUUID } = require("crypto");
const { URL } = require("url");

// ─── Configuration ────────────────────────────────────────────────────────────

function cfg(key) {
  let value = vscode.workspace.getConfiguration("smartdesk").get(key);
  if (typeof value === "string") {
    value = value.trim();
  }
  if (key === "userId" && !value) {
    return "local_user";
  }
  return value;
}

// ─── Constants ────────────────────────────────────────────────────────────────
const INGEST_PATH = "/api/v1/ingest/vscode/event";
const IDLE_THRESHOLD_MS = 2 * 60 * 1000; // 2 minutes without keystrokes = idle

// ─── State ────────────────────────────────────────────────────────────────────
let instanceId = randomUUID();
let sessionStart = null;
let lastActiveFile = null;
let lastWorkspace = null;

// Counters reset each session
let counters = newCounters();

// Idle tracking
let lastActivityTime = Date.now();
let idleStartTime = null;
let totalIdleSec = 0;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function newCounters() {
  return {
    edit_count: 0,
    save_count: 0,
    lines_added: 0,
    lines_deleted: 0,
    file_switch_count: 0,
    terminal_command_count: 0,
    debug_run_count: 0,
    idle_sec: 0,
  };
}

function nowIso() {
  return new Date().toISOString();
}

function getWorkspaceInfo() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  if (!folder) return { workspace_name: null, project_path: null };
  return {
    workspace_name: folder.name,
    project_path: folder.uri.fsPath,
  };
}

function getActiveFileInfo() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return {};
  const doc = editor.document;
  return {
    active_file_path: doc.uri.fsPath,
    active_file_name: doc.fileName.split(/[\\/]/).pop(),
    active_language: doc.languageId,
  };
}

function getProcessId() {
  return process.pid;
}

// ─── Offline retry queue ──────────────────────────────────────────────────────
const RETRY_QUEUE_MAX = 50;
const _retryQueue = [];

function postEvent(payload) {
  if (!cfg("enabled")) return;
  _sendOrQueue(payload);
}

function _sendOrQueue(payload) {
  const body = JSON.stringify(payload);
  const rawUrl = cfg("backendUrl");

  let parsedUrl;
  try {
    parsedUrl = new URL(rawUrl);
  } catch {
    console.warn("[SmartDesk] Invalid backendUrl:", rawUrl);
    return;
  }

  const options = {
    hostname: parsedUrl.hostname,
    port: parsedUrl.port || 8000,   // default SmartDesk port
    path: INGEST_PATH,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    },
  };

  const req = http.request(options, (res) => {
    let responseData = "";
    res.on("data", (chunk) => { responseData += chunk; });
    res.on("end", () => {
      if (res.statusCode >= 400) {
        console.error(`[SmartDesk] Event rejected (${res.statusCode}):`, responseData);
      } else if (_retryQueue.length > 0) {
        // On success: flush any queued events
        const queued = _retryQueue.splice(0);
        queued.forEach((p) => _sendOrQueue(p));
      }
    });
  });

  req.on("error", (e) => {
    console.error(`[SmartDesk] Network error:`, e.message);
    // Backend not reachable — queue for retry
    if (_retryQueue.length < RETRY_QUEUE_MAX) {
      _retryQueue.push(payload);
    }
  });

  req.setTimeout(4000, () => req.destroy());
  req.write(body);
  req.end();
}

// ─── Session lifecycle ────────────────────────────────────────────────────────

function startSession(trigger) {
  if (sessionStart) return; // Already in a session
  sessionStart = nowIso();
  totalIdleSec = 0;
  counters = newCounters();

  const ws = getWorkspaceInfo();
  const file = getActiveFileInfo();

  postEvent({
    user_id: cfg("userId"),
    event: "started",
    instance_id: instanceId,
    timestamp: sessionStart,
    process_id: getProcessId(),
    trigger: trigger || "activation",
    ...ws,
    ...file,
  });

  console.log("[SmartDesk] Session started.");
}

function endSession(trigger) {
  if (!sessionStart) return;
  const ws = getWorkspaceInfo();
  const file = getActiveFileInfo();

  // Flush any remaining idle time
  if (idleStartTime) {
    totalIdleSec += Math.floor((Date.now() - idleStartTime) / 1000);
    idleStartTime = null;
  }
  counters.idle_sec = totalIdleSec;

  postEvent({
    user_id: cfg("userId"),
    event: "ended",
    instance_id: instanceId,
    timestamp: nowIso(),
    process_id: getProcessId(),
    trigger: trigger || "deactivation",
    ...ws,
    ...file,
    counters,
  });

  console.log("[SmartDesk] Session ended.");
  sessionStart = null;
  counters = newCounters();
}

// ─── Activity tracking ────────────────────────────────────────────────────────

function recordActivity() {
  const now = Date.now();

  // Recover from idle
  if (idleStartTime) {
    totalIdleSec += Math.floor((now - idleStartTime) / 1000);
    idleStartTime = null;
  }

  lastActivityTime = now;
}

function checkIdle() {
  const now = Date.now();
  const elapsed = now - lastActivityTime;

  if (elapsed >= IDLE_THRESHOLD_MS && !idleStartTime) {
    // Just went idle
    idleStartTime = lastActivityTime + IDLE_THRESHOLD_MS;
  }
}

// ─── Extension activation ─────────────────────────────────────────────────────

function activate(context) {
  console.log("[SmartDesk] Extension activating...");

  // Start a session immediately if a workspace/file is open
  if (
    vscode.workspace.workspaceFolders?.length ||
    vscode.window.activeTextEditor
  ) {
    startSession("activation");
  }

  // ── Subscriptions ──────────────────────────────────────────────────────────

  // Text edits
  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.uri.scheme !== "file") return;
      recordActivity();
      if (!sessionStart) startSession("edit");

      e.contentChanges.forEach((change) => {
        counters.edit_count++;
        const lines = change.text.split("\n").length - 1;
        counters.lines_added += lines;
        const removed = change.rangeLength > 0 ? 1 : 0;
        counters.lines_deleted += removed;
      });
    })
  );

  // File saves
  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.uri.scheme !== "file") return;
      recordActivity();
      counters.save_count++;
    })
  );

  // Active editor change (file switch)
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor) return;
      const newFile = editor.document.uri.fsPath;
      if (newFile !== lastActiveFile) {
        recordActivity();
        if (!sessionStart) startSession("file_switch");
        counters.file_switch_count++;
        lastActiveFile = newFile;
      }
    })
  );

  // Terminal activity
  context.subscriptions.push(
    vscode.window.onDidOpenTerminal(() => {
      recordActivity();
      counters.terminal_command_count++;
    })
  );

  // Debug session started
  context.subscriptions.push(
    vscode.debug.onDidStartDebugSession(() => {
      recordActivity();
      counters.debug_run_count++;
    })
  );

  // Window focus lost → end session
  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((state) => {
      if (!state.focused) {
        endSession("blur");
      } else {
        recordActivity();
        if (!sessionStart) startSession("focus");
      }
    })
  );

  // Workspace folder change → end + restart session
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      endSession("workspace_change");
      setTimeout(() => startSession("workspace_open"), 200);
    })
  );

  // Idle check timer — runs every 30 seconds
  const idleTimer = setInterval(checkIdle, 30_000);
  context.subscriptions.push({ dispose: () => clearInterval(idleTimer) });

  console.log("[SmartDesk] Extension active.");
}

function deactivate() {
  endSession("shutdown");
  console.log("[SmartDesk] Extension deactivated.");
}

module.exports = { activate, deactivate };
