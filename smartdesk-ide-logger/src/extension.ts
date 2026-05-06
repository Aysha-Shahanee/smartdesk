import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

type ActiveEditorInfo = {
	file_path: string | null;
	file_name: string | null;
	language: string | null;
};

type MinuteWindowCounters = {
	ide_foreground_sec: number;
	active_editor_sec: number;
	idle_sec: number;
	edit_count: number;
	save_count: number;
	file_switch_count: number;
	terminal_command_count: number;
	debug_run_count: number;
	lines_added: number;
	lines_deleted: number;
};

type VSCodeMinuteWindowPayload = {
	user_id: string;
	window_start: string;
	window_end: string;
	timezone: string;
	workspace_name: string;
	project_path: string;
	repo_id: string | null;
	git_branch: string | null;
	active_file_path: string | null;
	active_file_name: string | null;
	active_language: string | null;
	ide_foreground_sec: number | null;
	active_editor_sec: number | null;
	idle_sec: number | null;
	edit_count: number;
	save_count: number;
	file_switch_count: number;
	terminal_command_count: number;
	debug_run_count: number;
	lines_added: number;
	lines_deleted: number;
	source: string;
};

const WINDOW_SECONDS = 60;
const WINDOW_MS = WINDOW_SECONDS * 1000;
const TICK_MS = 1000;
const IDLE_THRESHOLD_MS = 90 * 1000; // 90s grace period

// ─── Dynamic Timezone Helpers ───

function getTimezone(): string {
	return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function toLocalISOString(date: Date): string {
	// Use the system timezone offset dynamically
	const offsetMs = -date.getTimezoneOffset() * 60 * 1000;
	const local = new Date(date.getTime() + offsetMs);
	const sign = offsetMs >= 0 ? "+" : "-";
	const absOffset = Math.abs(date.getTimezoneOffset());
	const hh = String(Math.floor(absOffset / 60)).padStart(2, "0");
	const mm = String(absOffset % 60).padStart(2, "0");
	return local.toISOString().replace("Z", `${sign}${hh}:${mm}`);
}

function alignToLocalMinute(ms: number): number {
	const offsetMs = -new Date().getTimezoneOffset() * 60 * 1000;
	const shifted = ms + offsetMs;
	const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
	return aligned - offsetMs;
}

// ─── Repo ID Hashing (don't expose raw git URLs) ───

function hashRepoId(remoteUrl: string): string {
	let hash = 0;
	for (let i = 0; i < remoteUrl.length; i++) {
		const char = remoteUrl.charCodeAt(i);
		hash = ((hash << 5) - hash) + char;
		hash = hash & hash; // 32-bit int
	}
	return Math.abs(hash).toString(16).padStart(8, "0");
}

// ─── Helpers ───

function getRelativePath(filePath: string): string {
	const folders = vscode.workspace.workspaceFolders;
	if (folders && folders.length > 0) {
		const root = folders[0].uri.fsPath;
		if (filePath.toLowerCase().startsWith(root.toLowerCase())) {
			return path.relative(root, filePath).replace(/\\/g, "/");
		}
	}
	return path.basename(filePath);
}

function getWorkspaceName(): string {
	return vscode.workspace.workspaceFolders?.[0]?.name ?? "unknown-workspace";
}

function getProjectPath(): string {
	return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "";
}

function getUserId(): string {
	const configured = vscode.workspace.getConfiguration("smartdesk").get<string>("userId");
	if (configured && configured.trim()) { return configured.trim(); }
	return os.hostname(); // fallback: machine hostname
}

function getBackendUrl(): string {
	return vscode.workspace.getConfiguration("smartdesk").get<string>("backendUrl")
		?? "http://localhost:8000";
}

function getGitInfo(projectPath: string): { repo_id: string | null; git_branch: string | null } {
	if (!projectPath) {
		return { repo_id: null, git_branch: null };
	}

	const gitDir = path.join(projectPath, ".git");
	if (!fs.existsSync(gitDir)) {
		return { repo_id: null, git_branch: null };
	}

	let gitBranch: string | null = null;
	try {
		const headPath = path.join(gitDir, "HEAD");
		const head = fs.readFileSync(headPath, "utf8").trim();
		if (head.startsWith("ref:")) {
			const parts = head.split("/");
			gitBranch = parts[parts.length - 1] ?? null;
		} else if (head) {
			gitBranch = head.substring(0, 7);
		}
	} catch {
		gitBranch = null;
	}

	let repoId: string | null = null;
	try {
		const configPath = path.join(gitDir, "config");
		const config = fs.readFileSync(configPath, "utf8");
		const originBlock = config.split(/\[remote "origin"\]/i)[1];
		if (originBlock) {
			const urlMatch = originBlock.match(/url\s*=\s*(.+)/i);
			if (urlMatch) {
				// Hash the URL — don't send raw git URLs to the backend
				repoId = hashRepoId(urlMatch[1].trim());
			}
		}
	} catch {
		repoId = null;
	}

	return { repo_id: repoId, git_branch: gitBranch };
}

export function activate(context: vscode.ExtensionContext) {
	const output = vscode.window.createOutputChannel("SmartDesk Logger");
	context.subscriptions.push(output);
	output.appendLine(`[SmartDesk] Activated at ${new Date().toISOString()}`);

	let windowStartMs = 0;
	let windowEndMs = 0;
	let windowTimer: NodeJS.Timeout | null = null;
	let windowInterval: NodeJS.Timeout | null = null;
	let activityTimer: NodeJS.Timeout | null = null;
	let lastActivityMs = Date.now();
	let isWindowFocused = vscode.window.state.focused;
	let lastActiveFilePath: string | null = null;
	let activeEditorInfo: ActiveEditorInfo = {
		file_path: null,
		file_name: null,
		language: null
	};

	let counters: MinuteWindowCounters = createEmptyCounters();

	// Offline buffering — queue failed payloads for retry
	const pendingQueue: VSCodeMinuteWindowPayload[] = [];

	function createEmptyCounters(): MinuteWindowCounters {
		return {
			ide_foreground_sec: 0,
			active_editor_sec: 0,
			idle_sec: 0,
			edit_count: 0,
			save_count: 0,
			file_switch_count: 0,
			terminal_command_count: 0,
			debug_run_count: 0,
			lines_added: 0,
			lines_deleted: 0
		};
	}

	function resetCounters() {
		counters = createEmptyCounters();
	}

	function updateActiveEditor(editor?: vscode.TextEditor) {
		if (!editor || editor.document.isUntitled) { return; }

		const filePath = getRelativePath(editor.document.fileName);
		if (lastActiveFilePath && lastActiveFilePath !== filePath) {
			counters.file_switch_count += 1;
		}

		activeEditorInfo = {
			file_path: filePath,
			file_name: path.basename(editor.document.fileName),
			language: editor.document.languageId
		};

		lastActiveFilePath = filePath;
		lastActivityMs = Date.now();
	}

	function startActivityTimer() {
		stopActivityTimer();
		activityTimer = setInterval(() => {
			if (!windowStartMs) { return; }
			const now = Date.now();
			if (isWindowFocused) {
				counters.ide_foreground_sec += 1;
				if (lastActivityMs > 0 && now - lastActivityMs <= IDLE_THRESHOLD_MS) {
					counters.active_editor_sec += 1;
				} else {
					counters.idle_sec += 1;
				}
			} else {
				counters.idle_sec += 1;
			}
		}, TICK_MS);
	}

	function stopActivityTimer() {
		if (activityTimer) {
			clearInterval(activityTimer);
			activityTimer = null;
		}
	}

	async function sendMinuteWindow(payload: VSCodeMinuteWindowPayload) {
		const toSend = [...pendingQueue, payload];
		pendingQueue.length = 0;

		for (const p of toSend) {
			try {
				const res = await fetch(`${getBackendUrl()}/api/v1/ide/minute-window`, {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify(p)
				});
				if (!res.ok) { throw new Error(`HTTP ${res.status}`); }
			} catch (error) {
				const errMessage = error instanceof Error ? error.message : String(error);
				output.appendLine(`[SmartDesk] Send failed, queued for retry: ${errMessage}`);
				pendingQueue.push(p); // re-queue for next minute
			}
		}
	}

	function buildPayload(): VSCodeMinuteWindowPayload {
		const projectPath = getProjectPath();
		const gitInfo = getGitInfo(projectPath);

		return {
			user_id: getUserId(),
			window_start: toLocalISOString(new Date(windowStartMs)),
			window_end: toLocalISOString(new Date(windowEndMs)),
			timezone: getTimezone(),
			workspace_name: getWorkspaceName(),
			project_path: projectPath,
			repo_id: gitInfo.repo_id,
			git_branch: gitInfo.git_branch,
			active_file_path: activeEditorInfo.file_path,
			active_file_name: activeEditorInfo.file_name,
			active_language: activeEditorInfo.language,
			ide_foreground_sec: counters.ide_foreground_sec,
			active_editor_sec: counters.active_editor_sec,
			idle_sec: counters.idle_sec,
			edit_count: counters.edit_count,
			save_count: counters.save_count,
			file_switch_count: counters.file_switch_count,
			terminal_command_count: counters.terminal_command_count,
			debug_run_count: counters.debug_run_count,
			lines_added: counters.lines_added,
			lines_deleted: counters.lines_deleted,
			source: "vscode_extension",
		};
	}

	function flushWindow() {
		if (!windowStartMs || !windowEndMs) { return; }
		const payload = buildPayload();
		sendMinuteWindow(payload);
		resetCounters();
	}

	function stopWindowCycle() {
		if (windowTimer) {
			clearTimeout(windowTimer);
			windowTimer = null;
		}
		if (windowInterval) {
			clearInterval(windowInterval);
			windowInterval = null;
		}
	}

	function startWindowCycle() {
		stopWindowCycle();
		const now = Date.now();
		windowStartMs = alignToLocalMinute(now);
		windowEndMs = windowStartMs + WINDOW_MS;
		resetCounters();

		const delay = Math.max(0, windowEndMs - now);
		windowTimer = setTimeout(() => {
			flushWindow();
			windowStartMs = windowEndMs;
			windowEndMs = windowStartMs + WINDOW_MS;
			resetCounters();
			windowInterval = setInterval(() => {
				flushWindow();
				windowStartMs = windowEndMs;
				windowEndMs = windowStartMs + WINDOW_MS;
				resetCounters();
			}, WINDOW_MS);
		}, delay);
	}

	// --- Event Listeners ---
	const fileSwitch = vscode.window.onDidChangeActiveTextEditor(editor => {
		updateActiveEditor(editor);
	});

	// Track ALL text document changes — this fires for user edits, Copilot
	// completions, auto-format, extension-generated edits, and any other
	// programmatic modifications. Every content change is captured.
	const editTracking = vscode.workspace.onDidChangeTextDocument(e => {
		if (e.contentChanges.length === 0) { return; }
		if (vscode.window.activeTextEditor?.document !== e.document) { return; }

		// Count lines added/deleted from all content changes.
		// This captures user edits, Copilot completions, auto-format,
		// extension edits — any mutation to the document.
		let added = 0;
		let deleted = 0;
		for (const change of e.contentChanges) {
			const newLines = change.text.split("\n").length - 1;
			const oldLines = change.range.end.line - change.range.start.line;
			added += Math.max(0, newLines - oldLines);
			deleted += Math.max(0, oldLines - newLines);
		}
		counters.lines_added += added;
		counters.lines_deleted += deleted;

		// Count 1 per change event (not contentChanges.length which overcounts auto-format)
		counters.edit_count += 1;
		lastActivityMs = Date.now();
	});

	const saveTracking = vscode.workspace.onDidSaveTextDocument(doc => {
		if (vscode.window.activeTextEditor?.document !== doc) { return; }
		counters.save_count += 1;
		lastActivityMs = Date.now();
	});

	const debugTracking = vscode.debug.onDidStartDebugSession(() => {
		counters.debug_run_count += 1;
		lastActivityMs = Date.now();
	});

	const terminalTracking = vscode.window.onDidStartTerminalShellExecution?.(() => {
		counters.terminal_command_count += 1;
		lastActivityMs = Date.now();
	});

	const windowFocus = vscode.window.onDidChangeWindowState(state => {
		isWindowFocused = state.focused;
		lastActivityMs = isWindowFocused ? Date.now() : 0;
	});

	context.subscriptions.push(
		fileSwitch,
		editTracking,
		saveTracking,
		debugTracking,
		windowFocus
	);

	if (terminalTracking) { context.subscriptions.push(terminalTracking); }

	context.subscriptions.push({
		dispose: () => {
			stopWindowCycle();
			stopActivityTimer();
		}
	});

	if (vscode.window.activeTextEditor) {
		updateActiveEditor(vscode.window.activeTextEditor);
	}

	startWindowCycle();
	startActivityTimer();
}

export function deactivate() { }
