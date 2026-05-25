// SmartDesk VS Code Extension - v2.0.0
// Session-based architecture: emits "started", "state", and "ended" events.

const vscode = require("vscode");
const http = require("http");
const https = require("https");
const path = require("path");
const { execFileSync } = require("child_process");
const { createHash, randomUUID } = require("crypto");
const { URL } = require("url");

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

const INGEST_PATH = "/api/v1/ingest/vscode/event";
const IDLE_THRESHOLD_MS = 2 * 60 * 1000;
const STATE_INTERVAL_MS = 45 * 1000;
const RETRY_QUEUE_MAX = 50;
const MAX_CHANGED_FILES = 500;
const IGNORED_PATH_PARTS = new Set([
  ".git",
  "node_modules",
  ".venv",
  "venv",
  "__pycache__",
  ".pytest_cache",
  "dist",
  "build",
]);
const IGNORED_FILE_NAMES = new Set([
  "smartdesk.db",
  "smartdesk.db-journal",
  "smartdesk.db-shm",
  "smartdesk.db-wal",
]);
const IGNORED_FILE_EXTENSIONS = new Set([
  ".db",
  ".db-journal",
  ".db-shm",
  ".db-wal",
  ".sqlite",
  ".sqlite3",
  ".pyc",
]);

let instanceId = randomUUID();
let sessionStart = null;
let lastActiveFile = null;
let counters = newCounters();
let lastActivityTime = Date.now();
let idleStartTime = null;
let totalIdleSec = 0;

const retryQueue = [];
const changedFiles = new Map();
const fileEventCounts = { created: 0, modified: 0, deleted: 0 };

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
  const now = new Date();
  const offsetMin = -now.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const absOffsetMin = Math.abs(offsetMin);
  const hh = String(Math.floor(absOffsetMin / 60)).padStart(2, "0");
  const mm = String(absOffsetMin % 60).padStart(2, "0");
  const local = new Date(now.getTime() + offsetMin * 60000);
  return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function runGit(args, cwd) {
  try {
    return execFileSync("git", args, {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      timeout: 2000,
    }).trim();
  } catch {
    return null;
  }
}

function getWorkspaceFolder() {
  return vscode.workspace.workspaceFolders?.[0] || null;
}

function getGitInfo(projectPath) {
  if (!projectPath) {
    return { repo_id: null, git_branch: null };
  }

  const repoRoot = runGit(["rev-parse", "--show-toplevel"], projectPath) || projectPath;
  const remoteUrl = runGit(["config", "--get", "remote.origin.url"], repoRoot);
  const branch =
    runGit(["branch", "--show-current"], repoRoot) ||
    runGit(["rev-parse", "--abbrev-ref", "HEAD"], repoRoot);
  const repoIdSource = remoteUrl || repoRoot;

  return {
    repo_id: repoIdSource ? sha256(repoIdSource) : null,
    git_branch: branch || null,
  };
}

function getWorkspaceInfo() {
  const folder = getWorkspaceFolder();
  if (!folder) {
    return {
      workspace_name: null,
      project_path: null,
      repo_id: null,
      git_branch: null,
    };
  }

  const projectPath = folder.uri.fsPath;
  return {
    workspace_name: folder.name,
    project_path: projectPath,
    ...getGitInfo(projectPath),
  };
}

function getActiveFileInfo() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== "file") return {};
  const doc = editor.document;
  return {
    active_file_path: doc.uri.fsPath,
    active_file_name: path.basename(doc.fileName),
    active_language: doc.languageId,
  };
}

function getProcessId() {
  return process.pid;
}

function relativeWorkspacePath(filePath) {
  const folder = getWorkspaceFolder();
  if (!folder) return filePath;
  const rel = path.relative(folder.uri.fsPath, filePath);
  return rel && !rel.startsWith("..") && !path.isAbsolute(rel) ? rel : filePath;
}

function shouldTrackFile(filePath) {
  const rel = relativeWorkspacePath(filePath);
  const parts = rel.split(/[\\/]+/).filter(Boolean);
  const fileName = path.basename(filePath).toLowerCase();
  return (
    !parts.some((part) => IGNORED_PATH_PARTS.has(part)) &&
    !IGNORED_FILE_NAMES.has(fileName) &&
    !Array.from(IGNORED_FILE_EXTENSIONS).some((ext) => fileName.endsWith(ext))
  );
}

function recordFileEvent(uri, eventType) {
  if (!uri || uri.scheme !== "file" || !shouldTrackFile(uri.fsPath)) return;

  const relPath = relativeWorkspacePath(uri.fsPath);
  const existing = changedFiles.get(relPath) || {
    path: relPath,
    created: 0,
    modified: 0,
    deleted: 0,
  };

  existing[eventType] += 1;
  changedFiles.set(relPath, existing);
  fileEventCounts[eventType] += 1;

  if (changedFiles.size > MAX_CHANGED_FILES) {
    const firstKey = changedFiles.keys().next().value;
    changedFiles.delete(firstKey);
  }
}

function getExtraData() {
  return {
    changed_files: Array.from(changedFiles.values()),
    changed_file_count: changedFiles.size,
    file_event_counts: { ...fileEventCounts },
  };
}

function currentPayload(event, trigger) {
  if (idleStartTime) {
    counters.idle_sec =
      totalIdleSec + Math.floor((Date.now() - idleStartTime) / 1000);
  } else {
    counters.idle_sec = totalIdleSec;
  }

  return {
    user_id: cfg("userId"),
    event,
    instance_id: instanceId,
    timestamp: nowIso(),
    process_id: getProcessId(),
    trigger,
    ...getWorkspaceInfo(),
    ...getActiveFileInfo(),
    counters,
    extra_data: getExtraData(),
  };
}

function postEvent(payload) {
  if (!cfg("enabled")) return;
  sendOrQueue(payload);
}

function sendOrQueue(payload) {
  const body = JSON.stringify(payload);
  const rawUrl = cfg("backendUrl");

  let parsedUrl;
  try {
    parsedUrl = new URL(rawUrl);
  } catch {
    console.warn("[SmartDesk] Invalid backendUrl:", rawUrl);
    return;
  }

  const isHttps = parsedUrl.protocol === "https:";
  const transport = isHttps ? https : http;
  const basePath = parsedUrl.pathname && parsedUrl.pathname !== "/"
    ? parsedUrl.pathname.replace(/\/$/, "")
    : "";

  const options = {
    hostname: parsedUrl.hostname,
    port: parsedUrl.port || (isHttps ? 443 : 8000),
    path: `${basePath}${INGEST_PATH}`,
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
    },
  };

  const req = transport.request(options, (res) => {
    let responseData = "";
    res.on("data", (chunk) => {
      responseData += chunk;
    });
    res.on("end", () => {
      if (res.statusCode >= 400) {
        console.error(`[SmartDesk] Event rejected (${res.statusCode}):`, responseData);
      } else if (retryQueue.length > 0) {
        const queued = retryQueue.splice(0);
        queued.forEach((p) => sendOrQueue(p));
      }
    });
  });

  req.on("error", (e) => {
    console.error("[SmartDesk] Network error:", e.message);
    if (retryQueue.length < RETRY_QUEUE_MAX) {
      retryQueue.push(payload);
    }
  });

  req.setTimeout(4000, () => req.destroy());
  req.write(body);
  req.end();
}

function resetSessionTracking() {
  totalIdleSec = 0;
  counters = newCounters();
  changedFiles.clear();
  fileEventCounts.created = 0;
  fileEventCounts.modified = 0;
  fileEventCounts.deleted = 0;
}

function startSession(trigger) {
  if (sessionStart) return;
  sessionStart = nowIso();
  resetSessionTracking();
  postEvent({ ...currentPayload("started", trigger || "activation"), timestamp: sessionStart });
  console.log("[SmartDesk] Session started.");
}

function sendState(trigger) {
  if (!sessionStart) return;
  postEvent(currentPayload("state", trigger || "heartbeat"));
}

function endSession(trigger) {
  if (!sessionStart) return;
  if (idleStartTime) {
    totalIdleSec += Math.floor((Date.now() - idleStartTime) / 1000);
    idleStartTime = null;
  }
  counters.idle_sec = totalIdleSec;
  postEvent(currentPayload("ended", trigger || "deactivation"));
  console.log("[SmartDesk] Session ended.");
  sessionStart = null;
  resetSessionTracking();
}

function recordActivity() {
  const now = Date.now();
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
    idleStartTime = lastActivityTime + IDLE_THRESHOLD_MS;
  }
}

function activate(context) {
  console.log("[SmartDesk] Extension activating...");

  if (vscode.workspace.workspaceFolders?.length || vscode.window.activeTextEditor) {
    startSession("activation");
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.uri.scheme !== "file") return;
      recordActivity();
      if (!sessionStart) startSession("edit");
      recordFileEvent(e.document.uri, "modified");

      e.contentChanges.forEach((change) => {
        counters.edit_count += 1;
        counters.lines_added += Math.max(0, change.text.split("\n").length - 1);
        counters.lines_deleted += Math.max(0, change.range.end.line - change.range.start.line);
      });
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.uri.scheme !== "file") return;
      recordActivity();
      if (!sessionStart) startSession("save");
      recordFileEvent(doc.uri, "modified");
      counters.save_count += 1;
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor || editor.document.uri.scheme !== "file") return;
      const newFile = editor.document.uri.fsPath;
      if (newFile !== lastActiveFile) {
        recordActivity();
        if (!sessionStart) startSession("file_switch");
        counters.file_switch_count += 1;
        lastActiveFile = newFile;
      }
    })
  );

  const watcher = vscode.workspace.createFileSystemWatcher("**/*");
  context.subscriptions.push(
    watcher,
    watcher.onDidCreate((uri) => {
      const hasActiveEditor =
        vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.uri.scheme === "file";
      if (!hasActiveEditor && !sessionStart) return;
      recordActivity();
      if (!sessionStart) startSession("file_create");
      recordFileEvent(uri, "created");
    }),
    watcher.onDidChange((uri) => {
      const hasActiveEditor =
        vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.uri.scheme === "file";
      if (!hasActiveEditor && !sessionStart) return;
      recordActivity();
      if (!sessionStart) startSession("file_change");
      recordFileEvent(uri, "modified");
    }),
    watcher.onDidDelete((uri) => {
      const hasActiveEditor =
        vscode.window.activeTextEditor &&
        vscode.window.activeTextEditor.document.uri.scheme === "file";
      if (!hasActiveEditor && !sessionStart) return;
      recordActivity();
      if (!sessionStart) startSession("file_delete");
      recordFileEvent(uri, "deleted");
    })
  );

  context.subscriptions.push(
    vscode.window.onDidOpenTerminal(() => {
      recordActivity();
      if (!sessionStart) startSession("terminal");
      counters.terminal_command_count += 1;
    })
  );

  context.subscriptions.push(
    vscode.debug.onDidStartDebugSession(() => {
      recordActivity();
      if (!sessionStart) startSession("debug");
      counters.debug_run_count += 1;
    })
  );

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

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      endSession("workspace_change");
      setTimeout(() => startSession("workspace_open"), 200);
    })
  );

  const idleTimer = setInterval(checkIdle, 30_000);
  const stateTimer = setInterval(() => sendState("heartbeat"), STATE_INTERVAL_MS);
  context.subscriptions.push(
    { dispose: () => clearInterval(idleTimer) },
    { dispose: () => clearInterval(stateTimer) }
  );

  console.log("[SmartDesk] Extension active.");
}

function deactivate() {
  endSession("shutdown");
  console.log("[SmartDesk] Extension deactivated.");
}

module.exports = { activate, deactivate };
