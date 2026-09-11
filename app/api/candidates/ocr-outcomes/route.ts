import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

type OutcomeItem = {
  video_id?: string;
  outcome?: "matched" | "no_consensus" | "error";
  attempted_at?: string | null;
  attempts?: number | null;
};

export async function POST(request: Request) {
  if (!request.headers.get("oai-authenticated-user-id")) {
    return Response.json({ error: "Authentication required" }, { status: 401 });
  }
  const payload = await request.json() as { outcomes?: OutcomeItem[] };
  const items = Array.isArray(payload.outcomes)
    ? payload.outcomes.filter(item => item.video_id && item.outcome).slice(0, 500)
    : [];
  if (!items.length) return Response.json({ received: 0, updated: 0 });

  const statements = items.map(item => env.DB.prepare(`UPDATE candidates SET
      raw_metadata = json_set(
        CASE WHEN json_valid(raw_metadata) THEN raw_metadata ELSE '{}' END,
        '$.ocr_outcome', ?, '$.ocr_attempted_at', ?, '$.ocr_attempts', ?
      ), updated_at = CURRENT_TIMESTAMP
    WHERE video_id = ?
      AND status IN ('ready_for_review','time_required','classification_required')`)
    .bind(item.outcome, item.attempted_at ?? null, item.attempts ?? 1, item.video_id));
  const results = await env.DB.batch(statements);
  const updated = results.reduce((total, result) => total + (result.meta.changes ?? 0), 0);
  return Response.json({ received: items.length, updated });
}
