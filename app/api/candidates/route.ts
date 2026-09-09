import { env } from "cloudflare:workers";
import { shouldAutoApproveTitle } from "@/lib/candidate-policy";

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
        ORDER BY confidence DESC, created_at ASC LIMIT 500`).all(),
      db().prepare(`SELECT id, character, category, floor, time_ms,
        player_nick, era_key, video_url, channel FROM (
          SELECT r.id, r.character, r.category, r.floor, r.time_ms,
            r.player_nick, r.era_key, c.video_url, c.channel,
            ROW_NUMBER() OVER (
              PARTITION BY r.era_key, r.category, r.floor, r.character, r.player_nick
              ORDER BY r.time_ms ASC, r.approved_at ASC, r.id ASC
            ) AS nick_position
          FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ) WHERE nick_position = 1
        ORDER BY era_key DESC, category, floor, character, time_ms`).all(),
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
  let updated = 0;
  let autoApproved = 0;
  for (const item of items) {
    if (!item.video_id || !item.video_url || !item.title || !item.status) continue;
    const autoApprove = shouldAutoApproveTitle(item);
    const effectiveStatus = autoApprove ? "approved" : item.status;
    const rawMetadata = typeof item.raw_metadata === "string"
      ? item.raw_metadata
      : JSON.stringify(item.raw_metadata ?? {});
    const result = await db().prepare(`INSERT OR IGNORE INTO candidates
      (video_id, video_url, title, channel, player_nick, published_at, character,
       category, floor, time_ms, confidence, status, era_key, raw_metadata)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(item.video_id, item.video_url, item.title, item.channel ?? null,
        item.player_nick ?? item.channel ?? null, item.published_at ?? null,
        item.character ?? null, item.category ?? null, item.floor ?? null,
        item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
        item.era_key ?? "current", rawMetadata).run();
    if ((result.meta.changes ?? 0) > 0) {
      inserted += 1;
    } else {
      const update = await db().prepare(`UPDATE candidates SET
          video_url = ?, title = ?, channel = COALESCE(?, channel),
          player_nick = COALESCE(?, player_nick), published_at = COALESCE(?, published_at),
          character = COALESCE(?, character), category = COALESCE(?, category),
          floor = COALESCE(?, floor), time_ms = ?, confidence = ?, status = ?, raw_metadata = ?,
          updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
          AND ? IS NOT NULL
          AND status IN ('ready_for_review','time_required','classification_required')`)
        .bind(item.video_url, item.title, item.channel ?? null,
          item.player_nick ?? item.channel ?? null, item.published_at ?? null,
          item.character ?? null, item.category ?? null, item.floor ?? null,
          item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
          rawMetadata, item.video_id, item.time_ms ?? null).run();
      updated += update.meta.changes ?? 0;
    }
    if (autoApprove) {
      const ranking = await db().prepare(`INSERT OR IGNORE INTO rankings
        (candidate_id, character, category, floor, time_ms, player_nick, era_key)
        SELECT id, character, category, floor, time_ms,
          COALESCE(player_nick, channel, 'Desconhecido'), era_key
        FROM candidates
        WHERE video_id = ? AND status = 'approved'
          AND character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL AND time_ms IS NOT NULL`).bind(item.video_id).run();
      autoApproved += ranking.meta.changes ?? 0;
    }
  }
  return Response.json({ received: items.length, inserted, updated, auto_approved: autoApproved });
}
