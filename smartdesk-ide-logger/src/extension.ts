import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

type SessionEvent = {
	event_id: string;
	file_path?: string;
	language?: string;

	start_time: string;
	end_time?: string;
	duration_seconds?: number;

	active_seconds: number;
	idle_seconds: number;

	edit_count: number;
	save_count: number;
	debug_runs: number;

	approx_lines_added: number;
	approx_lines_removed: number;
	approx_chars_added: number;
	approx_chars_removed: number;

	terminal_commands: number;
};

type ProjectLog = {
	project_name: string;
	project_path: string;
	sessions: SessionEvent[];
};

const AUTO_SAVE_INTERVAL = 30000;
const IDLE_THRESHOLD = 90 * 1000; // 90s grace period

function nowLocalIso() {
	const d = new Date();
	const pad = (n: number) => String(n).padStart(2, "0");
	const ms = String(d.getMilliseconds()).padStart(3, "0");

	const tzOffset = -d.getTimezoneOffset();
	const tzSign = tzOffset >= 0 ? "+" : "-";
	const tzHours = pad(Math.floor(Math.abs(tzOffset) / 60));
	const tzMins = pad(Math.abs(tzOffset) % 60);
	const tz = `${tzSign}${tzHours}:${tzMins}`;

	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
		d.getHours()
	)}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${ms}${tz}`;
}

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

export function activate(context: vscode.ExtensionContext) {
	const output = vscode.window.createOutputChannel("SmartDesk Logger");
	context.subscriptions.push(output);
	output.appendLine(`[SmartDesk] Activated at ${new Date().toISOString()}`);

	const storagePath = context.globalStorageUri.fsPath;
	if (!fs.existsSync(storagePath)) { fs.mkdirSync(storagePath, { recursive: true }); }

	const logFilePath = path.join(storagePath, "ide_events.json");
	if (!fs.existsSync(logFilePath)) {
		fs.writeFileSync(logFilePath, JSON.stringify([], null, 2), "utf8");
	}

	function readLogs(): ProjectLog[] {
		try {
			const data = JSON.parse(fs.readFileSync(logFilePath, "utf8"));
			if (!Array.isArray(data)) { return []; }

			// Already in ProjectLog[] format
			if (data.length > 0 && (data[0] as any).sessions) {
				return data;
			}

			// Migrate old flat SessionEvent[] format
			if (data.length > 0 && (data[0] as any).event_id) {
				const migrated: ProjectLog[] = [{
					project_name: getProjectName(),
					project_path: getProjectPath(),
					sessions: data as SessionEvent[]
				}];
				writeLogs(migrated);
				return migrated;
			}

			return [];
		} catch { }
		return [];
	}

	function writeLogs(logs: ProjectLog[]) {
		fs.writeFileSync(logFilePath, JSON.stringify(logs, null, 2), "utf8");
	}

	function getProjectName(): string {
		return vscode.workspace.workspaceFolders?.[0]?.name ?? "unknown-project";
	}

	function getProjectPath(): string {
		return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? "";
	}

	async function sendToBackend(session: SessionEvent) {
		try {
			const payload = {
				timestamp: new Date().toISOString(),
				event_type: "vscode_session",
				data: {
					project_name: getProjectName(),
					project_path: getProjectPath(),
					...session
				}
			};

			// Fire an HTTP POST request to the local backend
			await fetch("http://localhost:8000/api/v1/vscode/", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload)
			});
		} catch (error) {
			const errMessage = error instanceof Error ? error.message : String(error);
			output.appendLine(`[SmartDesk] Backend sync failed: ${errMessage}`);
		}
	}

	function upsertSession(session: SessionEvent) {
		const logs = readLogs();
		let project = logs.find(p => p.project_path === getProjectPath());
		if (!project) {
			project = {
				project_name: getProjectName(),
				project_path: getProjectPath(),
				sessions: []
			};
			logs.push(project);
		}

		const idx = project.sessions.findIndex(s => s.event_id === session.event_id);
		if (idx >= 0) { project.sessions[idx] = session; }
		else { project.sessions.push(session); }

		writeLogs(logs);

		// Send non-blocking update to backend
		sendToBackend(session);
	}

	function isSessionDoc(doc: vscode.TextDocument): boolean {
		if (!currentSession) { return false; }
		// Case-insensitive comparison for Windows (VS Code can report different casing)
		return getRelativePath(doc.fileName).toLowerCase() === currentSession.file_path?.toLowerCase();
	}

	let currentSession: SessionEvent | null = null;
	let sessionStartMs = 0;
	let autoSaveTimer: NodeJS.Timeout | null = null;
	let activityTimer: NodeJS.Timeout | null = null;
	let lastActivityTimestamp = Date.now();

	function createEmptySession(doc: vscode.TextDocument): SessionEvent {
		return {
			event_id: `evt_${Date.now()}`,
			file_path: getRelativePath(doc.fileName),
			language: doc.languageId,

			start_time: nowLocalIso(),
			end_time: undefined,
			duration_seconds: undefined,

			active_seconds: 0,
			idle_seconds: 0,

			edit_count: 0,
			save_count: 0,
			debug_runs: 0,

			approx_lines_added: 0,
			approx_lines_removed: 0,
			approx_chars_added: 0,
			approx_chars_removed: 0,

			terminal_commands: 0
		};
	}

	function startActivityMonitor() {
		stopActivityMonitor();
		activityTimer = setInterval(() => {
			if (!currentSession) { return; }
			const now = Date.now();

			if (now - lastActivityTimestamp > IDLE_THRESHOLD) {
				currentSession.idle_seconds += 1;
			} else {
				currentSession.active_seconds += 1;
			}
		}, 1000);
	}

	function stopActivityMonitor() {
		if (activityTimer) {
			clearInterval(activityTimer);
			activityTimer = null;
		}
	}

	function startAutoSaveTimer() {
		stopAutoSaveTimer();
		autoSaveTimer = setInterval(() => {
			if (!currentSession) { return; }
			const snapshot = { ...currentSession };
			snapshot.end_time = nowLocalIso();
			snapshot.duration_seconds = Math.max(1, Math.floor((Date.now() - sessionStartMs) / 1000));
			upsertSession(snapshot);
		}, AUTO_SAVE_INTERVAL);
	}

	function stopAutoSaveTimer() {
		if (autoSaveTimer) {
			clearInterval(autoSaveTimer);
			autoSaveTimer = null;
		}
	}

	function startSession(editor: vscode.TextEditor) {
		if (editor.document.isUntitled) { return; }

		currentSession = createEmptySession(editor.document);
		sessionStartMs = Date.now();
		lastActivityTimestamp = Date.now();

		startAutoSaveTimer();
		startActivityMonitor();

		output.appendLine(`[SmartDesk] Session started: ${currentSession.file_path}`);
	}

	function endSession() {
		if (!currentSession) { return; }

		stopAutoSaveTimer();
		stopActivityMonitor();

		currentSession.end_time = nowLocalIso();
		currentSession.duration_seconds = Math.max(1, Math.floor((Date.now() - sessionStartMs) / 1000));

		upsertSession(currentSession);

		output.appendLine(`[SmartDesk] Session ended: ${currentSession.file_path}`);

		currentSession = null;
		sessionStartMs = 0;
	}

	// --- Event Listeners ---

	const fileSwitch = vscode.window.onDidChangeActiveTextEditor(editor => {
		endSession();
		if (!editor) { return; }

		const fullPath = editor.document.fileName;
		if (fullPath === logFilePath) { return; }
		if (fullPath.toLowerCase().endsWith(".json")) { return; }

		startSession(editor);
	});

	const editTracking = vscode.workspace.onDidChangeTextDocument(e => {
		if (!currentSession) { return; }

		// Skip events with no actual content changes (metadata-only events)
		if (e.contentChanges.length === 0) { return; }

		if (!isSessionDoc(e.document)) {
			// Log mismatch for debugging
			output.appendLine(`[SmartDesk] Edit SKIPPED: doc="${getRelativePath(e.document.fileName)}" session="${currentSession.file_path}"`);
			return;
		}

		currentSession.edit_count += e.contentChanges.length;
		lastActivityTimestamp = Date.now();

		for (const change of e.contentChanges) {
			currentSession.approx_chars_added += change.text.length;
			currentSession.approx_chars_removed += change.rangeLength;

			const added = (change.text.match(/\n/g) || []).length;
			const removed = Math.max(0, change.range.end.line - change.range.start.line);

			currentSession.approx_lines_added += added;
			currentSession.approx_lines_removed += removed;
		}
	});

	const saveTracking = vscode.workspace.onDidSaveTextDocument(doc => {
		if (!currentSession || !isSessionDoc(doc)) { return; }
		currentSession.save_count += 1;
		lastActivityTimestamp = Date.now();
	});

	const debugTracking = vscode.debug.onDidStartDebugSession(() => {
		if (!currentSession) { return; }
		currentSession.debug_runs += 1;
		lastActivityTimestamp = Date.now();
	});

	const terminalTracking = vscode.window.onDidStartTerminalShellExecution?.(() => {
		if (!currentSession) { return; }
		currentSession.terminal_commands += 1;
		lastActivityTimestamp = Date.now();
	});

	const windowFocus = vscode.window.onDidChangeWindowState(state => {
		if (!currentSession) { return; }

		if (!state.focused) {
			lastActivityTimestamp = 0; // force idle
		} else {
			lastActivityTimestamp = Date.now();
		}
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
			endSession();
		}
	});

	const showLogLocation = vscode.commands.registerCommand(
		"smartdesk.showLogLocation",
		() => {
			vscode.window.showInformationMessage(`SmartDesk log file: ${logFilePath}`);
		}
	);

	context.subscriptions.push(showLogLocation);

	if (vscode.window.activeTextEditor) {
		startSession(vscode.window.activeTextEditor);
	}
}

export function deactivate() { }
