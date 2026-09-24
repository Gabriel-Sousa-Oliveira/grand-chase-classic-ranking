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

async function githubRequest(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = githubHeaders();
  if (!headers) {
    return Response.json({ error: "GitHub workflow token is not configured" }, { status: 503 });
  }
  return fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: { ...headers, ...init.headers },
    cache: "no-store",
  });
}

async function recentRuns(): Promise<GitHubWorkflowRun[] | Response> {
  const response = await githubRequest(`/actions/workflows/${WORKFLOW}/runs?per_page=10`);
  if (!response.ok) {
    return Response.json({ error: "GitHub Actions is unavailable" }, { status: response.status });
  }
  const payload = await response.json() as { workflow_runs?: GitHubWorkflowRun[] };
  return Array.isArray(payload.workflow_runs) ? payload.workflow_runs : [];
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
  const denied = authorize(request);
  if (denied) return denied;
  const runs = await recentRuns();
  if (runs instanceof Response) return runs;
  return Response.json({ run: publicRun(runs[0] ?? null) });
}

export async function POST(request: Request) {
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
    return Response.json({ error: "Could not start the crawler" }, { status: dispatched.status });
  }
  return Response.json({ status: "queued", days }, { status: 202 });
}
