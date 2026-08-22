/**
 * The preload bridge, as the renderer sees it.
 *
 * Optional throughout: the pages also run in a plain browser during `vite dev`
 * where no preload exists, and the action buttons degrade to recording
 * feedback rather than crashing.
 */
export interface SmartDeskElectronAPI {
  getEnv: () => { backendUrl: string };
  /** Open an https://github.com link in the system browser. */
  openGitHubExternal: (url: string) => Promise<void>;
  /** Open the Google OAuth consent URL in the system browser. */
  openCalendarExternal: (url: string) => Promise<void>;
  startBreak: (minutes?: number) => Promise<boolean>;
  resumeTask: (facts: Record<string, unknown>) => Promise<boolean>;
  exportReportPdf: (scope: string, date?: string) => Promise<string | null>;
  notificationSettings: (patch?: Record<string, unknown>) => Promise<{
    enabled: boolean;
    quietFrom: number;
    quietTo: number;
    muted: string[];
    shownToday: number;
  }>;
}

declare global {
  interface Window {
    electronAPI?: SmartDeskElectronAPI;
  }
}

export {};
