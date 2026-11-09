import { env } from "cloudflare:workers";
import { failureReasons, outcomeUpdateSql } from "@/lib/ocr-diagnostics";

export const dynamic = "force-dynamic";

type OutcomeItem = {
  video_id?: string; outcome?: string; result?: string;
  attempted_at?: string | null; ocr_attempted_at?: string | null;
  attempts?: number | null; ocr_attempts?: number | null;
  failure_reason?: string | null; ocr_version?: string | null;
  evidence_seconds?: number | null; evidence_image?: string | null;
  ocr_diagnostics?: Record<string, unknown> | null;
};

export async function POST(request: Request) {
  const expected = (env as unknown as { INGEST_API_TOKEN?: string }).INGEST_API_TOKEN;
  const token = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!request.headers.get("oai-authenticated-user-id") && !(expected && token === expected)) {
    return Response.json({ error: "Authentication required" }, { status: 401 });
  }
  let payload: { outcomes?: OutcomeItem[] };
  try { payload = await request.json(); }
  catch { return Response.json({ error: "Invalid JSON" }, { status: 400 }); }
  const items = Array.isArray(payload?.outcomes) ? payload.outcomes.slice(0, 500) : [];
  const now = new Date().toISOString();
  const statements = [];
  for (const item of items) {
    if (!item || typeof item.video_id !== "string" || !item.video_id) continue;
    const outcome = item.outcome ?? item.result;
    if (!["matched", "no_consensus", "error"].includes(outcome ?? "")) continue;
    const attempts = item.ocr_attempts ?? item.attempts ?? 1;
    const attemptedAt = item.ocr_attempted_at ?? item.attempted_at ?? now;
    if (!Number.isSafeInteger(attempts) || attempts < 1 ||
        !Number.isFinite(Date.parse(attemptedAt))) continue;
    const reason = outcome === "matched" ? null : item.failure_reason ??
      (outcome === "error" ? "technical_error" : "timer_not_frozen_or_not_readable");
    if (reason !== null && !failureReasons.includes(reason as typeof failureReasons[number])) continue;
    if (item.evidence_seconds != null && (!Number.isFinite(item.evidence_seconds) || item.evidence_seconds < 0)) continue;
    if (item.ocr_version != null && (typeof item.ocr_version !== "string" || item.ocr_version.length > 100)) continue;
    if (item.evidence_image != null && (typeof item.evidence_image !== "string" || item.evidence_image.length > 500)) continue;
    if (item.ocr_diagnostics != null && (typeof item.ocr_diagnostics !== "object" || Array.isArray(item.ocr_diagnostics) || JSON.stringify(item.ocr_diagnostics).length > 4000)) continue;
    const timestamp = new Date(attemptedAt).toISOString();
    const metadata: Record<string, unknown> = {
      ocr_outcome: outcome, ocr_attempted_at: timestamp, failure_reason: reason,
    };
    // Missing optional fields must preserve existing evidence, including on
    // legacy repairs. Explicit null can clear evidence from a newer attempt.
    for (const key of ["ocr_version", "evidence_seconds", "evidence_image", "ocr_diagnostics"] as const) {
      if (item[key] !== undefined) metadata[key] = item[key];
    }
    statements.push(env.DB.prepare(outcomeUpdateSql)
      .bind(JSON.stringify(metadata), attempts, item.video_id, timestamp));
  }
  if (!statements.length) return Response.json({ received: 0, updated: 0 });
  const results = await env.DB.batch(statements);
  return Response.json({ received: statements.length,
    updated: results.reduce((total, result) => total + (result.meta.changes ?? 0), 0) });
}
