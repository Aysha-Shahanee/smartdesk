// SmartDesk IDE Extension - v3.1.2
// Session-based architecture: emits "started", "state", and "ended" events.
//
// Works in any VS Code-based IDE (VS Code, Antigravity, Cursor, Windsurf...).
// Collection rules:
//   - IDE window focused           -> collect normally (foreground).
//   - IDE blurred but edits arrive -> AI working in background: keep
//     collecting, flagged is_window_focused=false (backend stores
//     is_foreground=0 / collection_reason=background_ai).
//   - IDE blurred and idle         -> session ends after a grace period;
//     nothing is collected until focus or activity returns.

const vscode = require("vscode");
const http = require("http");
const https = require("https");
const path = require("path");
const { execFileSync } = require("child_process");
const { createHash, randomUUID } = require("crypto");
const { URL } = require("url");
const { normalizeGitHubRepository } = require("./repository");

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

const INGEST_PATH = "/api/v1/ingest/ide/event";
const IDLE_THRESHOLD_MS = 2 * 60 * 1000;
const STATE_INTERVAL_MS = 45 * 1000;
// How long the IDE may stay blurred with no edit activity before the
// session is closed (covers short blips and background AI pauses).
const BLUR_GRACE_MS = 60 * 1000;
const RETRY_QUEUE_MAX = 50;
const MAX_CHANGED_FILES = 500;
const MAX_EDITED_FILES = 200;
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
let windowFocused = vscode.window.state ? vscode.window.state.focused : true;
let lastEditActivityTime = Date.now();

const retryQueue = [];
const changedFiles = new Map(); // disk-level changes (file watcher)
const editedFiles = new Map();  // editor-level edits, incl. AI edits to non-active files
const fileEventCounts = { created: 0, modified: 0, deleted: 0 };

function newCounters() {
  return {
    edit_count: 0,
    save_count: 0,
    lines_added: 0,
    lines_deleted: 0,
    file_switch_count: 0,
    idle_sec: 0,
  };
}

function getIdeName() {
  const appName = (vscode.env.appName || "").toLowerCase();
  if (appName.includes("antigravity")) return "antigravity";
  if (appName.includes("cursor")) return "cursor";
  if (appName.includes("windsurf")) return "windsurf";
  if (appName.includes("visual studio code")) return "vscode";
  return appName.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "unknown_ide";
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

function getWorkspaceFolder(filePath) {
  if (filePath) {
    const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(filePath));
    if (folder) return folder;
  }
  return vscode.workspace.workspaceFolders?.[0] || null;
}

function getGitInfo(searchPath) {
  if (!searchPath) {
    return { repo_id: null, repository: null, git_branch: null };
  }

  const repoRoot = runGit(["rev-parse", "--show-toplevel"], searchPath);
  if (!repoRoot) {
    return { repo_id: null, repository: null, git_branch: null };
  }
  const remoteUrl = runGit(["config", "--get", "remote.origin.url"], repoRoot);
  const branch =
    runGit(["branch", "--show-current"], repoRoot) ||
    runGit(["rev-parse", "--abbrev-ref", "HEAD"], repoRoot);
  const repoIdSource = remoteUrl || repoRoot;

  return {
    repo_id: repoIdSource ? sha256(repoIdSource) : null,
    repository: normalizeGitHubRepository(remoteUrl),
    // In detached HEAD, git reports "HEAD". Preserve no branch rather than
    // implying that it is a usable task-attribution branch.
    git_branch: branch && branch !== "HEAD" ? branch : null,
  };
}

function getWorkspaceInfo(filePath) {
  const folder = getWorkspaceFolder(filePath);
  if (!folder) {
    return {
      workspace_name: null,
      project_path: null,
      repo_id: null,
      repository: null,
      git_branch: null,
    };
  }

  const projectPath = folder.uri.fsPath;
  const searchPath = filePath ? path.dirname(filePath) : projectPath;
  return {
    workspace_name: folder.name,
    project_path: projectPath,
    ...getGitInfo(searchPath),
  };
}

let lastActiveFileInfo = {};

// Falls back to the last-known file so heartbeats fired while focus sits on
// a non-editor panel (terminal, chat, settings) don't blank these fields.
function getActiveFileInfo() {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.uri.scheme !== "file") return lastActiveFileInfo;
  const doc = editor.document;
  lastActiveFileInfo = {
    active_file_path: doc.uri.fsPath,
    active_file_name: path.basename(doc.fileName),
    active_language: doc.languageId,
  };
  return lastActiveFileInfo;
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

function recordEditedFile(doc, linesAdded, linesDeleted) {
  if (!shouldTrackFile(doc.uri.fsPath)) return;

  const relPath = relativeWorkspacePath(doc.uri.fsPath);
  const entry = editedFiles.get(relPath) || {
    path: relPath,
    language: doc.languageId,
    edits: 0,
    lines_added: 0,
    lines_deleted: 0,
    by_ai_while_blurred: false,
  };

  entry.language = doc.languageId;
  entry.edits += 1;
  entry.lines_added += linesAdded;
  entry.lines_deleted += linesDeleted;
  if (!windowFocused) {
    entry.by_ai_while_blurred = true;
  }
  editedFiles.set(relPath, entry);

  if (editedFiles.size > MAX_EDITED_FILES) {
    const firstKey = editedFiles.keys().next().value;
    editedFiles.delete(firstKey);
  }
}

function languageBreakdown() {
  const langs = {};
  for (const entry of editedFiles.values()) {
    const lang = entry.language || "unknown";
    langs[lang] = (langs[lang] || 0) + entry.edits;
  }
  return langs;
}

function dominantLanguage(langs) {
  let best = null;
  let bestCount = 0;
  for (const [lang, count] of Object.entries(langs)) {
    if (count > bestCount) {
      best = lang;
      bestCount = count;
    }
  }
  return best;
}

function getExtraData() {
  return {
    changed_files: Array.from(changedFiles.values()),
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

  const langs = languageBreakdown();

  const activeFile = getActiveFileInfo();
  return {
    user_id: cfg("userId"),
    event,
    instance_id: instanceId,
    timestamp: nowIso(),
    ide_name: getIdeName(),
    process_id: process.pid,
    parent_process_id: process.ppid || null,
    is_window_focused: windowFocused,
    trigger,
    ...getWorkspaceInfo(activeFile.active_file_path),
    ...activeFile,
    counters,
    edited_file_count: editedFiles.size,
    changed_file_count: changedFiles.size,
    dominant_language: dominantLanguage(langs),
    languages_json: langs,
    edited_files_json: Array.from(editedFiles.values()),
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
  // Drop any idle baseline carried over from a previous or blurred period.
  // Without this, idle that accrued before the session existed leaked into
  // the new row on the next refocus (producing idle_sec > duration_sec).
  idleStartTime = null;
  lastActivityTime = Date.now();
  lastEditActivityTime = Date.now();
  counters = newCounters();
  changedFiles.clear();
  editedFiles.clear();
  fileEventCounts.created = 0;
  fileEventCounts.modified = 0;
  fileEventCounts.deleted = 0;
}

function startSession(trigger) {
  if (sessionStart) return;
  sessionStart = nowIso();
  resetSessionTracking();
  postEvent({ ...currentPayload("started", trigger || "activation"), timestamp: sessionStart });
  console.log("[SmartDesk] Session started:", trigger);
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
  console.log("[SmartDesk] Session ended:", trigger);
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

// Edit-shaped activity (typing, AI edits, saves, file changes). This is the
// signal that keeps a blurred session alive — focus alone is handled by
// recordActivity().
function recordEditActivity() {
  recordActivity();
  lastEditActivityTime = Date.now();
}

function checkIdle() {
  // Idle only accrues inside a focused session. Time spent blurred or
  // between sessions is not idle: the row is closed at the blur boundary,
  // and AI work in a blurred window arrives as edits (activity), not idle.
  // Gating here also stops idle from a prior away-period from leaking into
  // the next session.
  if (!sessionStart || !windowFocused) return;

  const now = Date.now();
  const elapsed = now - lastActivityTime;

  // Count the whole inactivity stretch from the last real activity (not from
  // threshold + onward). This also captures laptop-sleep gaps: while
  // suspended the timer is frozen and no input or AI edits occur, so on the
  // first tick after resume the full gap is attributed to idle.
  if (elapsed >= IDLE_THRESHOLD_MS && !idleStartTime) {
    idleStartTime = lastActivityTime;
  }
}

// While blurred: end the session once no edits arrived for BLUR_GRACE_MS.
// While AI keeps editing in the background, the session stays open and is
// reported with is_window_focused=false.
function checkBlurredSession() {
  if (windowFocused || !sessionStart) return;
  if (Date.now() - lastEditActivityTime >= BLUR_GRACE_MS) {
    endSession("blur_idle");
  }
}

function activate(context) {
  console.log(`[SmartDesk] Extension activating in ${getIdeName()}...`);

  if (vscode.workspace.workspaceFolders?.length || vscode.window.activeTextEditor) {
    startSession("activation");
  }

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (e.document.uri.scheme !== "file") return;
      recordEditActivity();
      // Edits while blurred mean an AI agent is working — keep collecting.
      if (!sessionStart) startSession(windowFocused ? "edit" : "background_ai_edit");
      recordFileEvent(e.document.uri, "modified");

      let linesAdded = 0;
      let linesDeleted = 0;
      e.contentChanges.forEach((change) => {
        counters.edit_count += 1;
        const added = Math.max(0, change.text.split("\n").length - 1);
        const deleted = Math.max(0, change.range.end.line - change.range.start.line);
        counters.lines_added += added;
        counters.lines_deleted += deleted;
        linesAdded += added;
        linesDeleted += deleted;
      });
      recordEditedFile(e.document, linesAdded, linesDeleted);
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.uri.scheme !== "file") return;
      recordEditActivity();
      if (!sessionStart) startSession(windowFocused ? "save" : "background_ai_save");
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
        if (!sessionStart && windowFocused) startSession("file_switch");
        counters.file_switch_count += 1;
        lastActiveFile = newFile;
      }
    })
  );

  const watcher = vscode.workspace.createFileSystemWatcher("**/*");
  context.subscriptions.push(
    watcher,
    // The watcher fires for EVERY file in the workspace, including writes the
    // user never made: the SmartDesk backend churns smartdesk.db-wal/-journal
    // continuously when it runs inside this workspace. Gate the whole handler
    // on shouldTrackFile FIRST — otherwise recordEditActivity() reset the
    // blur-grace timer on that churn and kept blurred sessions alive for
    // hours (the multi-hour background_ai rows). The ignore filter inside
    // recordFileEvent ran too late to prevent that.
    watcher.onDidCreate((uri) => {
      if (uri.scheme !== "file" || !shouldTrackFile(uri.fsPath)) return;
      if (!sessionStart && !windowFocused) return;
      recordEditActivity();
      if (!sessionStart) startSession("file_create");
      recordFileEvent(uri, "created");
    }),
    watcher.onDidChange((uri) => {
      if (uri.scheme !== "file" || !shouldTrackFile(uri.fsPath)) return;
      if (!sessionStart && !windowFocused) return;
      recordEditActivity();
      if (!sessionStart) startSession("file_change");
      recordFileEvent(uri, "modified");
    }),
    watcher.onDidDelete((uri) => {
      if (uri.scheme !== "file" || !shouldTrackFile(uri.fsPath)) return;
      if (!sessionStart && !windowFocused) return;
      recordEditActivity();
      if (!sessionStart) startSession("file_delete");
      recordFileEvent(uri, "deleted");
    })
  );

  context.subscriptions.push(
    vscode.window.onDidOpenTerminal(() => {
      recordActivity();
      if (!sessionStart && windowFocused) startSession("terminal");
    })
  );

  context.subscriptions.push(
    vscode.debug.onDidStartDebugSession(() => {
      recordActivity();
      if (!sessionStart && windowFocused) startSession("debug");
    })
  );

  // Keyboard/mouse activity that isn't an edit: cursor moves, clicks, text
  // selection. Without this, reading or navigating a file (no edits) let idle
  // accrue even though the user was clearly active. Gate on the change kind so
  // AI/command-driven selection changes don't count as user activity (and edits
  // already reset idle via onDidChangeTextDocument). Reset idle only — don't
  // start a session, so passive reading never manufactures a new row.
  context.subscriptions.push(
    vscode.window.onDidChangeTextEditorSelection((e) => {
      if (!sessionStart || !windowFocused) return;
      const kind = e.kind;
      if (
        kind === vscode.TextEditorSelectionChangeKind.Keyboard ||
        kind === vscode.TextEditorSelectionChangeKind.Mouse
      ) {
        recordActivity();
      }
    })
  );

  // Scrolling (mouse wheel / keyboard) — pure navigation, also counts as the
  // user being active.
  context.subscriptions.push(
    vscode.window.onDidChangeTextEditorVisibleRanges(() => {
      if (!sessionStart || !windowFocused) return;
      recordActivity();
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeWindowState((state) => {
      // VS Code emits redundant window-state events (the focus value doesn't
      // actually change — e.g. on internal popups/quick-inputs). Ignore those:
      // otherwise each one closes+reopens a 0-second sliver row ("by refocus").
      if (state.focused === windowFocused) return;
      windowFocused = state.focused;
      if (state.focused) {
        recordActivity();
        // A session that was open while blurred is background-AI work —
        // close it so foreground work starts a clean row (one row never
        // mixes foreground and background time).
        if (sessionStart) endSession("refocus");
        startSession("focus");
      } else if (sessionStart) {
        // Close the foreground row at the blur boundary. If AI keeps
        // editing in the background, the next edit opens a new session
        // flagged is_window_focused=false (background_ai).
        endSession("blur");
        lastEditActivityTime = Date.now();
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
  const blurTimer = setInterval(checkBlurredSession, 15_000);
  const stateTimer = setInterval(() => sendState("heartbeat"), STATE_INTERVAL_MS);
  context.subscriptions.push(
    { dispose: () => clearInterval(idleTimer) },
    { dispose: () => clearInterval(blurTimer) },
    { dispose: () => clearInterval(stateTimer) }
  );

  console.log("[SmartDesk] Extension active.");
}

function deactivate() {
  endSession("shutdown");
  console.log("[SmartDesk] Extension deactivated.");
}

module.exports = { activate, deactivate };
