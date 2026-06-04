// SmartDesk VS Code Extension - v2.0.0
// Session-based architecture: emits "started", "state", and "ended" events.

const vscode = require("vscode");
const http = require("http");
const https = require("https");
const path = require("path");
const { execFileSync } = require("child_process");
const { createHash, randomUUID } = require("crypto");
const { URL } = require("url");
const fs = require("fs");

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
const editedFiles = new Map();
const fileSnapshots = new Map();
const recentChangeCache = new Map();
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

function inferLanguageId(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  switch (ext) {
    case ".js": return "javascript";
    case ".ts": return "typescript";
    case ".jsx": return "javascriptreact";
    case ".tsx": return "typescriptreact";
    case ".py": return "python";
    case ".html": return "html";
    case ".css": return "css";
    case ".json": return "json";
    case ".md": return "markdown";
    case ".sh": return "shellscript";
    case ".yaml":
    case ".yml": return "yaml";
    case ".sql": return "sql";
    default: return ext.slice(1) || "plaintext";
  }
}

function diffContent(oldText, newText) {
  const oldLines = oldText.split(/\r?\n/);
  const newLines = newText.split(/\r?\n/);

  let i = 0;
  while (i < oldLines.length && i < newLines.length && oldLines[i] === newLines[i]) {
    i++;
  }

  let j = 0;
  while (j < oldLines.length - i && j < newLines.length - i && oldLines[oldLines.length - 1 - j] === newLines[newLines.length - 1 - j]) {
    j++;
  }

  const deleted = oldLines.length - i - j;
  const added = newLines.length - i - j;
  return { added: Math.max(0, added), deleted: Math.max(0, deleted) };
}

function readFileLinesAndContent(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      const content = fs.readFileSync(filePath, "utf8");
      const linesCount = content.split(/\r?\n/).length;
      return { content, linesCount };
    }
  } catch (err) {
    console.error(`[VSCode Tracker] Error reading file ${filePath}:`, err);
  }
  return { content: "", linesCount: 0 };
}

function getLanguagesSummary() {
  const languagesMap = new Map();
  for (const stats of editedFiles.values()) {
    const lang = stats.language || "unknown";
    let langStats = languagesMap.get(lang);
    if (!langStats) {
      langStats = { edit_count: 0, lines_added: 0, lines_deleted: 0 };
    }
    langStats.edit_count += stats.edit_count;
    langStats.lines_added += stats.lines_added;
    langStats.lines_deleted += stats.lines_deleted;
    languagesMap.set(lang, langStats);
  }

  let dominantLanguage = null;
  let maxLines = -1;
  let maxEdits = -1;

  for (const [lang, stats] of languagesMap.entries()) {
    const linesTotal = stats.lines_added + stats.lines_deleted;
    if (linesTotal > maxLines) {
      maxLines = linesTotal;
      maxEdits = stats.edit_count;
      dominantLanguage = lang;
    } else if (linesTotal === maxLines) {
      if (stats.edit_count > maxEdits) {
        maxEdits = stats.edit_count;
        dominantLanguage = lang;
      }
    }
  }

  return {
    languages_json: Object.fromEntries(languagesMap),
    dominant_language: dominantLanguage,
  };
}

function currentPayload(event, trigger) {
  if (idleStartTime) {
    counters.idle_sec =
      totalIdleSec + Math.floor((Date.now() - idleStartTime) / 1000);
  } else {
    counters.idle_sec = totalIdleSec;
  }

  const langSummary = getLanguagesSummary();

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

    // New session tracking fields
    edited_file_count: editedFiles.size,
    changed_file_count: changedFiles.size,
    total_edit_count: counters.edit_count,
    total_save_count: counters.save_count,
    total_lines_added: counters.lines_added,
    total_lines_deleted: counters.lines_deleted,
    dominant_language: langSummary.dominant_language,
    languages_json: langSummary.languages_json,
    edited_files_json: Array.from(editedFiles.values()),

    extra_data: getExtraData(),
  };
}

function postEvent(payload) {
  if (!cfg("enabled")) return;
  console.log("[SmartDesk] git info", { repo_id: payload.repo_id, git_branch: payload.git_branch });
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
  editedFiles.clear();
  fileSnapshots.clear();
  recentChangeCache.clear();
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

      const filePath = e.document.uri.fsPath;
      const isTracked = shouldTrackFile(filePath);
      const relPath = relativeWorkspacePath(filePath);
      const fileName = path.basename(filePath);
      const lang = e.document.languageId;

      let stats = null;
      if (isTracked) {
        stats = editedFiles.get(relPath) || {
          file_path: relPath,
          file_name: fileName,
          language: lang,
          edit_count: 0,
          save_count: 0,
          lines_added: 0,
          lines_deleted: 0,
        };
      }

      e.contentChanges.forEach((change) => {
        const added = Math.max(0, change.text.split("\n").length - 1);
        const deleted = Math.max(0, change.range.end.line - change.range.start.line);

        counters.edit_count += 1;
        counters.lines_added += added;
        counters.lines_deleted += deleted;

        if (stats) {
          stats.edit_count += 1;
          stats.lines_added += added;
          stats.lines_deleted += deleted;
        }
      });

      if (stats) {
        stats.change_source = "text_document";
        editedFiles.set(relPath, stats);

        const docContent = e.document.getText();
        fileSnapshots.set(relPath, docContent);
        recentChangeCache.set(relPath, Date.now());
        console.log("[VSCode Tracker] Text document changed: " + relPath);
        console.log("[VSCode Tracker] Updated edited_files_json: " + JSON.stringify(Array.from(editedFiles.values())));
      }

      recordFileEvent(e.document.uri, "modified");
    })
  );

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (doc.uri.scheme !== "file") return;
      recordActivity();
      if (!sessionStart) startSession("save");

      const filePath = doc.uri.fsPath;
      if (shouldTrackFile(filePath)) {
        const relPath = relativeWorkspacePath(filePath);
        const fileName = path.basename(filePath);
        const lang = doc.languageId;

        const stats = editedFiles.get(relPath) || {
          file_path: relPath,
          file_name: fileName,
          language: lang,
          edit_count: 0,
          save_count: 0,
          lines_added: 0,
          lines_deleted: 0,
        };
        stats.save_count += 1;
        stats.change_source = "text_document";
        editedFiles.set(relPath, stats);

        const docContent = doc.getText();
        fileSnapshots.set(relPath, docContent);
        recentChangeCache.set(relPath, Date.now());
        console.log("[VSCode Tracker] Text document changed (save): " + relPath);
      }

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
      if (uri.scheme !== "file") return;
      const filePath = uri.fsPath;
      if (!shouldTrackFile(filePath)) return;

      const relPath = relativeWorkspacePath(filePath);

      if (recentChangeCache.has(relPath)) {
        const lastTime = recentChangeCache.get(relPath);
        if (Date.now() - lastTime < 2000) {
          console.log(`[VSCode Tracker] File created (skipped duplicate): ${relPath}`);
          return;
        }
      }

      console.log(`[VSCode Tracker] File created: ${relPath}`);
      recordActivity();

      if (!sessionStart) {
        const hasActiveEditor =
          vscode.window.activeTextEditor &&
          vscode.window.activeTextEditor.document.uri.scheme === "file";
        if (!hasActiveEditor) return;
        startSession("file_create");
      }

      const fileName = path.basename(filePath);
      const lang = inferLanguageId(filePath);

      const { content, linesCount } = readFileLinesAndContent(filePath);
      fileSnapshots.set(relPath, content);
      recentChangeCache.set(relPath, Date.now());

      const stats = editedFiles.get(relPath) || {
        file_path: relPath,
        file_name: fileName,
        language: lang,
        edit_count: 0,
        save_count: 0,
        lines_added: 0,
        lines_deleted: 0,
      };

      stats.change_source = "filesystem_created";
      stats.edit_count += 1;
      stats.lines_added += linesCount;
      editedFiles.set(relPath, stats);

      counters.edit_count += 1;
      counters.lines_added += linesCount;

      recordFileEvent(uri, "created");
      console.log(`[VSCode Tracker] Updated edited_files_json: ` + JSON.stringify(Array.from(editedFiles.values())));
    }),
    watcher.onDidChange((uri) => {
      if (uri.scheme !== "file") return;
      const filePath = uri.fsPath;
      if (!shouldTrackFile(filePath)) return;

      const relPath = relativeWorkspacePath(filePath);

      if (recentChangeCache.has(relPath)) {
        const lastTime = recentChangeCache.get(relPath);
        if (Date.now() - lastTime < 2000) {
          console.log(`[VSCode Tracker] File changed (skipped duplicate): ${relPath}`);
          return;
        }
      }

      console.log(`[VSCode Tracker] File changed: ${relPath}`);
      recordActivity();

      if (!sessionStart) {
        const hasActiveEditor =
          vscode.window.activeTextEditor &&
          vscode.window.activeTextEditor.document.uri.scheme === "file";
        if (!hasActiveEditor) return;
        startSession("file_change");
      }

      const fileName = path.basename(filePath);
      const lang = inferLanguageId(filePath);

      const { content, linesCount } = readFileLinesAndContent(filePath);

      let added = 0;
      let deleted = 0;

      const prevContent = fileSnapshots.get(relPath);
      if (prevContent !== undefined && prevContent !== null) {
        const diff = diffContent(prevContent, content);
        added = diff.added;
        deleted = diff.deleted;
      } else {
        added = 0;
        deleted = 0;
      }

      fileSnapshots.set(relPath, content);
      recentChangeCache.set(relPath, Date.now());

      const stats = editedFiles.get(relPath) || {
        file_path: relPath,
        file_name: fileName,
        language: lang,
        edit_count: 0,
        save_count: 0,
        lines_added: 0,
        lines_deleted: 0,
      };

      stats.change_source = "filesystem_changed";
      stats.edit_count += 1;
      stats.lines_added += added;
      stats.lines_deleted += deleted;
      editedFiles.set(relPath, stats);

      counters.edit_count += 1;
      counters.lines_added += added;
      counters.lines_deleted += deleted;

      recordFileEvent(uri, "modified");
      console.log(`[VSCode Tracker] Updated edited_files_json: ` + JSON.stringify(Array.from(editedFiles.values())));
    }),
    watcher.onDidDelete((uri) => {
      if (uri.scheme !== "file") return;
      const filePath = uri.fsPath;
      if (!shouldTrackFile(filePath)) return;

      const relPath = relativeWorkspacePath(filePath);
      console.log(`[VSCode Tracker] File deleted: ${relPath}`);
      recordActivity();

      if (!sessionStart) {
        const hasActiveEditor =
          vscode.window.activeTextEditor &&
          vscode.window.activeTextEditor.document.uri.scheme === "file";
        if (!hasActiveEditor) return;
        startSession("file_delete");
      }

      fileSnapshots.delete(relPath);
      recentChangeCache.delete(relPath);

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


