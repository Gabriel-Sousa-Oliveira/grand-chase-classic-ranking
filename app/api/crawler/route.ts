import { env } from "cloudflare:workers";
import {
  cooldownRemainingSeconds,
  isActiveRun,
  parseLookbackDays,
  type GitHubWorkflowRun,
} from "@/lib/crawler-control";

export const dynamic = "force-dynamic";

const REPOSITORY = "Gabriel-Sousa-Oliveira/grand-chase-classic-ranking";
const WORKFLOW = "youtube-crawler.yml";
const API_ROOT = `https://api.github.com/repos/${REPOSITORY}`;

type RuntimeEnv = {
  ADMIN_EMAIL?: string;
  GITHUB_WORKFLOW_TOKEN?: string;
  INGEST_API_TOKEN?: string;
};

type CrawlReport = {
  run_number?: number;
  created_at?: string;
  queries?: number;
  seed_discovered_unique?: number;
  channels_expanded?: number;
  channel_uploads_scanned?: number;
  discovered_unique?: number;
  duplicates?: number;
  ignored?: number;
  created?: number;
};

function runtimeEnv(): RuntimeEnv {
  return env as unknown as RuntimeEnv;
}

function authorize(request: Request): Response | null {
  const userId = request.headers.get("oai-authenticated-user-id");
  const email = request.headers.get("oai-authenticated-user-email")?.trim().toLowerCase();
  const adminEmail = runtimeEnv().ADMIN_EMAIL?.trim().toLowerCase();
  if (!userId || !email) {
    return Response.json({ error: "Authentication required" }, { status: 401 });
  }
  if (!adminEmail) {
    return Response.json({ error: "Crawler control is not configured" }, { status: 503 });
  }
  if (email !== adminEmail) {
    return Response.json({ error: "Administrator access required" }, { status: 403 });
  }
  return null;
}

function githubHeaders(): HeadersInit | null {
  const token = runtimeEnv().GITHUB_WORKFLOW_TOKEN;
  if (!token) return null;
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "gc-run-radar-admin",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

function database() {
  const binding = (env as unknown as { DB?: D1Database }).DB;
  if (!binding) throw new Error("Database unavailable");
  return binding;
}

async function ensureReportTable() {
  await database().prepare(
    "CREATE TABLE IF NOT EXISTS crawler_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, run_number INTEGER, report_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
  ).run();
}

async function latestReport(): Promise<CrawlReport | null> {
  await ensureReportTable();
  const row = await database().prepare(
    "SELECT report_json FROM crawler_reports ORDER BY id DESC LIMIT 1"
  ).first<{ report_json?: string }>();
  if (!row?.report_json) return null;
  try {
    return JSON.parse(row.report_json) as CrawlReport;
  } catch {
    return null;
  }
}

async function githubRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = githubHeaders();
  if (!headers) {
    return Response.json({ error: "GitHub workflow token is not configured" }, { status: 503 });
  }
  try {
    return await fetch(`${API_ROOT}${path}`, {
      ...init,
      headers: { ...headers, ...init.headers },
      cache: "no-store",
    });
  } catch (reason) {
    console.error("crawler.github_request_failed", reason);
    return Response.json(
      { error: "Could not connect to GitHub Actions" },
      { status: 502 },
    );
  }
}

async function recentRuns(): Promise<GitHubWorkflowRun[] | Response> {
  const response = await githubRequest(`/actions/workflows/${WORKFLOW}/runs?per_page=10`);
  if (!response.ok) {
    const details = await response.text().catch(() => "");
    console.error("crawler.github_runs_failed", response.status, details.slice(0, 500));
    return Response.json(
      { error: `GitHub Actions returned HTTP ${response.status}` },
      { status: response.status },
    );
  }
  try {
    const payload = await response.json() as { workflow_runs?: GitHubWorkflowRun[] };
    return Array.isArray(payload.workflow_runs) ? payload.workflow_runs : [];
  } catch (reason) {
    console.error("crawler.github_invalid_json", reason);
    return Response.json({ error: "GitHub Actions returned an invalid response" }, { status: 502 });
  }
}

function publicRun(run: GitHubWorkflowRun | null) {
  if (!run) return null;
  return {
    id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    url: run.html_url,
    event: run.event,
    created_at: run.created_at,
    updated_at: run.updated_at,
  };
}

export async function GET(request: Request) {
  try {
    const denied = authorize(request);
    if (denied) return denied;
    const runs = await recentRuns();
    if (runs instanceof Response) return runs;
    return Response.json({
      run: publicRun(runs[0] ?? null),
      report: await latestReport(),
    });
  } catch (reason) {
    console.error("crawler.status_failed", reason);
    return Response.json({ error: "Crawler status failed unexpectedly" }, { status: 500 });
  }
}

export async function PUT(request: Request) {
  try {
    const expected = runtimeEnv().INGEST_API_TOKEN;
    const supplied = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
    if (!expected || supplied !== expected) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
    const payload = await request.json() as CrawlReport;
    const report: CrawlReport = {
      run_number: Number(payload.run_number) || undefined,
      created_at: typeof payload.created_at === "string" ? payload.created_at : undefined,
      queries: Number(payload.queries) || 0,
      seed_discovered_unique: Number(payload.seed_discovered_unique) || 0,
      channels_expanded: Number(payload.channels_expanded) || 0,
      channel_uploads_scanned: Number(payload.channel_uploads_scanned) || 0,
      discovered_unique: Number(payload.discovered_unique) || 0,
      duplicates: Number(payload.duplicates) || 0,
      ignored: Number(payload.ignored) || 0,
      created: Number(payload.created) || 0,
    };
    await ensureReportTable();
    await database().prepare(
      "INSERT INTO crawler_reports (run_number, report_json) VALUES (?, ?)"
    ).bind(report.run_number ?? null, JSON.stringify(report)).run();
    await database().prepare(
      "DELETE FROM crawler_reports WHERE id NOT IN (SELECT id FROM crawler_reports ORDER BY id DESC LIMIT 30)"
    ).run();
    return Response.json({ stored: true }, { status: 201 });
  } catch (reason) {
    console.error("crawler.report_failed", reason);
    return Response.json({ error: "Could not store crawler report" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const denied = authorize(request);
    if (denied) return denied;
    const origin = request.headers.get("origin");
    if (!origin || origin !== new URL(request.url).origin) {
      return Response.json({ error: "Invalid request origin" }, { status: 403 });
    }

    let payload: { days?: unknown };
    try {
      payload = await request.json() as { days?: unknown };
    } catch {
      return Response.json({ error: "Invalid request" }, { status: 400 });
    }
    const days = parseLookbackDays(payload.days);
    if (!days) {
      return Response.json({ error: "Invalid search period" }, { status: 400 });
    }

    const runs = await recentRuns();
    if (runs instanceof Response) return runs;
    const active = runs.find(isActiveRun) ?? null;
    if (active) {
      return Response.json({ error: "A crawler run is already active", run: publicRun(active) }, { status: 409 });
    }
    const retryAfter = cooldownRemainingSeconds(runs);
    if (retryAfter > 0) {
      return Response.json(
        { error: "Crawler cooldown is active", retry_after_seconds: retryAfter, run: publicRun(runs[0] ?? null) },
        { status: 429, headers: { "Retry-After": String(retryAfter) } },
      );
    }

    const dispatched = await githubRequest(`/actions/workflows/${WORKFLOW}/dispatches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "main", inputs: { mode: "recent", days: String(days) } }),
    });
    if (!dispatched.ok) {
      const details = await dispatched.text().catch(() => "");
      console.error("crawler.github_dispatch_failed", dispatched.status, details.slice(0, 500));
      return Response.json(
        { error: `Could not start the crawler (HTTP ${dispatched.status})` },
        { status: dispatched.status },
      );
    }
    return Response.json({ status: "queued", days }, { status: 202 });
  } catch (reason) {
    console.error("crawler.start_failed", reason);
    return Response.json({ error: "Crawler start failed unexpectedly" }, { status: 500 });
  }
}
