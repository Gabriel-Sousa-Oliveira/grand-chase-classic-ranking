export const CRAWLER_LOOKBACK_DAYS = [1, 3, 7, 14, 30] as const;
export const CRAWLER_COOLDOWN_MS = 10 * 60 * 1000;

export type CrawlerLookbackDays = (typeof CRAWLER_LOOKBACK_DAYS)[number];
export type GitHubRunState = "queued" | "in_progress" | "completed";

export type GitHubWorkflowRun = {
  id: number;
  status: GitHubRunState;
  conclusion: string | null;
  html_url: string;
  event: string;
  created_at: string;
  updated_at: string;
};

export function parseLookbackDays(value: unknown): CrawlerLookbackDays | null {
  const days = typeof value === "number" ? value : Number(value);
  return CRAWLER_LOOKBACK_DAYS.includes(days as CrawlerLookbackDays)
    ? (days as CrawlerLookbackDays)
    : null;
}

export function isActiveRun(run: GitHubWorkflowRun | null): boolean {
  return run?.status === "queued" || run?.status === "in_progress";
}

export function cooldownRemainingSeconds(
  runs: GitHubWorkflowRun[],
  now = Date.now(),
): number {
  const latestManual = runs.find(run => run.event === "workflow_dispatch");
  if (!latestManual) return 0;
  const elapsed = now - Date.parse(latestManual.created_at);
  if (!Number.isFinite(elapsed) || elapsed >= CRAWLER_COOLDOWN_MS) return 0;
  return Math.ceil((CRAWLER_COOLDOWN_MS - elapsed) / 1000);
}
