import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

type ActiveEditorInfo = {
	file_path: string | null;
	file_name: string | null;
	language: string | null;
};

type MinuteWindowCounters = {
	vscode_foreground_sec: number;
	active_editor_sec: number;
	idle_sec: number;
	edit_count: number;
	save_count: number;
	file_switch_count: number;
	terminal_command_count: number;
	debug_run_count: number;
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
	vscode_foreground_sec: number | null;
	active_editor_sec: number | null;
	idle_sec: number | null;
	edit_count: number;
	save_count: number;
	file_switch_count: number;
	terminal_command_count: number;
	debug_run_count: number;
	source: string;
	schema_version: string;
	created_at: string;
	updated_at: string;
};

const WINDOW_SECONDS = 60;
const WINDOW_MS = WINDOW_SECONDS * 1000;
const TICK_MS = 1000;
const IDLE_THRESHOLD_MS = 90 * 1000; // 90s grace period
const SCHEMA_VERSION = "1.0";
const COLOMBO_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const COLOMBO_TIMEZONE = "Asia/Colombo";

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
	return process.env.USER_ID ?? "demo_user";
}

function getTimezone(): string {
	return COLOMBO_TIMEZONE;
}

function toColomboISOString(date: Date): string {
	const colomboDate = new Date(date.getTime() + COLOMBO_OFFSET_MS);
	const yyyy = colomboDate.getUTCFullYear();
	const mm = String(colomboDate.getUTCMonth() + 1).padStart(2, "0");
	const dd = String(colomboDate.getUTCDate()).padStart(2, "0");
	const hh = String(colomboDate.getUTCHours()).padStart(2, "0");
	const mi = String(colomboDate.getUTCMinutes()).padStart(2, "0");
	const ss = String(colomboDate.getUTCSeconds()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}T${hh}:${mi}:${ss}+05:30`;
}

function alignToColomboMinute(ms: number): number {
	const shifted = ms + COLOMBO_OFFSET_MS;
	const aligned = Math.floor(shifted / WINDOW_MS) * WINDOW_MS;
	return aligned - COLOMBO_OFFSET_MS;
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
				repoId = urlMatch[1].trim();
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

	function createEmptyCounters(): MinuteWindowCounters {
		return {
			vscode_foreground_sec: 0,
			active_editor_sec: 0,
			idle_sec: 0,
			edit_count: 0,
			save_count: 0,
			file_switch_count: 0,
			terminal_command_count: 0,
			debug_run_count: 0
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
				counters.vscode_foreground_sec += 1;
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
		try {
			await fetch("http://localhost:8000/api/v1/vscode/minute-window", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload)
			});
		} catch (error) {
			const errMessage = error instanceof Error ? error.message : String(error);
			output.appendLine(`[SmartDesk] Minute window sync failed: ${errMessage}`);
		}
	}

	function buildPayload(): VSCodeMinuteWindowPayload {
		const projectPath = getProjectPath();
		const gitInfo = getGitInfo(projectPath);
		const nowIso = toColomboISOString(new Date());

		return {
			user_id: getUserId(),
			window_start: toColomboISOString(new Date(windowStartMs)),
			window_end: toColomboISOString(new Date(windowEndMs)),
			timezone: getTimezone(),
			workspace_name: getWorkspaceName(),
			project_path: projectPath,
			repo_id: gitInfo.repo_id,
			git_branch: gitInfo.git_branch,
			active_file_path: activeEditorInfo.file_path,
			active_file_name: activeEditorInfo.file_name,
			active_language: activeEditorInfo.language,
			vscode_foreground_sec: counters.vscode_foreground_sec,
			active_editor_sec: counters.active_editor_sec,
			idle_sec: counters.idle_sec,
			edit_count: counters.edit_count,
			save_count: counters.save_count,
			file_switch_count: counters.file_switch_count,
			terminal_command_count: counters.terminal_command_count,
			debug_run_count: counters.debug_run_count,
			source: "vscode_extension",
			schema_version: SCHEMA_VERSION,
			created_at: nowIso,
			updated_at: nowIso
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
		windowStartMs = alignToColomboMinute(now);
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

	const editTracking = vscode.workspace.onDidChangeTextDocument(e => {
		if (e.contentChanges.length === 0) { return; }
		if (vscode.window.activeTextEditor?.document !== e.document) { return; }
		counters.edit_count += e.contentChanges.length;
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
