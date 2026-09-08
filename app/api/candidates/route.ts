import { env } from "cloudflare:workers";

export const dynamic = "force-dynamic";

type IncomingCandidate = {
  video_id?: string; video_url?: string; title?: string; channel?: string | null;
  player_nick?: string | null; published_at?: string | null; character?: string | null;
  category?: string | null; floor?: number | null; time_ms?: number | null;
  confidence?: number; status?: string; era_key?: string; raw_metadata?: unknown;
};

function db() {
  if (!env.DB) throw new Error("Database unavailable");
  return env.DB;
}

export async function GET() {
  try {
    const [queue, rankings] = await Promise.all([
      db().prepare(`SELECT id, video_id, video_url, title, channel, player_nick,
        published_at, character, category, floor, time_ms, confidence, status, era_key
        FROM candidates WHERE status IN ('ready_for_review','time_required','classification_required')
        ORDER BY confidence DESC, created_at ASC LIMIT 100`).all(),
      db().prepare(`SELECT r.id, r.character, r.category, r.floor, r.time_ms,
        r.player_nick, r.era_key, c.video_url, c.channel
        FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ORDER BY r.era_key DESC, r.category, r.floor, r.character, r.time_ms`).all(),
    ]);
    return Response.json({ candidates: queue.results, rankings: rankings.results });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Database error" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const expected = (env as unknown as { INGEST_API_TOKEN?: string }).INGEST_API_TOKEN;
  const supplied = request.headers.get("authorization")?.replace(/^Bearer\s+/i, "");
  if (!expected || supplied !== expected) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  const payload = await request.json() as { candidates?: IncomingCandidate[] };
  const items = Array.isArray(payload.candidates) ? payload.candidates.slice(0, 500) : [];
  let inserted = 0;
  for (const item of items) {
    if (!item.video_id || !item.video_url || !item.title || !item.status) continue;
    const result = await db().prepare(`INSERT OR IGNORE INTO candidates
      (video_id, video_url, title, channel, player_nick, published_at, character,
       category, floor, time_ms, confidence, status, era_key, raw_metadata)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(item.video_id, item.video_url, item.title, item.channel ?? null,
        item.player_nick ?? item.channel ?? null, item.published_at ?? null,
        item.character ?? null, item.category ?? null, item.floor ?? null,
        item.time_ms ?? null, item.confidence ?? 0, item.status,
        item.era_key ?? "current", JSON.stringify(item.raw_metadata ?? {})).run();
    inserted += result.meta.changes ?? 0;
  }
  return Response.json({ received: items.length, inserted });
}
