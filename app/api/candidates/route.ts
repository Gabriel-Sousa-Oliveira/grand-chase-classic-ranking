import { env } from "cloudflare:workers";
import { shouldAutoApproveTitle } from "@/lib/candidate-policy";
import { canonicalizePlayerNick } from "@/lib/player-nick";

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

async function backfillApprovedTitles() {
  const database = db();
  const eligible = `status = 'ready_for_review'
    AND character IS NOT NULL AND category IS NOT NULL
    AND floor IS NOT NULL AND floor >= 0
    AND time_ms IS NOT NULL AND time_ms > 0
    AND confidence >= 0.95`;
  await database.batch([
    database.prepare(`UPDATE candidates SET status = 'approved',
      updated_at = CURRENT_TIMESTAMP WHERE ${eligible}`),
    database.prepare(`INSERT OR IGNORE INTO rankings
      (candidate_id, character, category, floor, time_ms, player_nick, era_key)
      SELECT id, character, category, floor, time_ms,
        COALESCE(player_nick, channel, 'Desconhecido'), era_key
      FROM candidates WHERE status = 'approved'
        AND character IS NOT NULL AND category IS NOT NULL
        AND floor IS NOT NULL AND floor >= 0
        AND time_ms IS NOT NULL AND time_ms > 0
        AND confidence >= 0.95`),
  ]);
}

export async function GET() {
  try {
    await backfillApprovedTitles();
    const [queue, rankings, history, processing] = await Promise.all([
      db().prepare(`SELECT c.id, c.video_id, c.video_url, c.title, c.channel, c.player_nick,
        c.published_at, c.created_at, c.character, c.category, c.floor, c.time_ms,
        c.confidence, c.status, c.era_key,
        json_extract(c.raw_metadata, '$.ocr_outcome') AS ocr_outcome,
        EXISTS(SELECT 1 FROM candidates duplicate
          WHERE duplicate.id <> c.id AND c.time_ms IS NOT NULL
            AND duplicate.time_ms = c.time_ms
            AND duplicate.character = c.character
            AND duplicate.category = c.category
            AND duplicate.floor = c.floor
            AND lower(COALESCE(duplicate.player_nick, duplicate.channel, '')) =
              lower(COALESCE(c.player_nick, c.channel, ''))
        ) AS possible_duplicate,
        benchmark.avg_time AS benchmark_ms,
        benchmark.sample_size AS benchmark_count
        FROM candidates c
        LEFT JOIN (
          SELECT character, category, floor, AVG(time_ms) AS avg_time,
            COUNT(*) AS sample_size
          FROM rankings GROUP BY character, category, floor
        ) benchmark ON benchmark.character = c.character
          AND benchmark.category = c.category AND benchmark.floor = c.floor
        WHERE c.status IN ('ready_for_review','time_required','classification_required')
        ORDER BY c.confidence DESC, c.created_at ASC LIMIT 500`).all(),
      db().prepare(`SELECT id, character, category, floor, time_ms,
        player_nick, era_key, video_url, channel, published_at, approved_at FROM (
          SELECT r.id, r.character, r.category, r.floor, r.time_ms,
            r.player_nick, r.era_key, c.video_url, c.channel, c.published_at, r.approved_at,
            ROW_NUMBER() OVER (
              PARTITION BY r.era_key, r.category, r.floor, r.character, r.player_nick
              ORDER BY r.time_ms ASC, r.approved_at ASC, r.id ASC
            ) AS nick_position
          FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ) WHERE nick_position = 1
        ORDER BY category, floor, character, time_ms ASC, era_key DESC`).all(),
      db().prepare(`SELECT r.id, r.character, r.category, r.floor, r.time_ms,
        r.player_nick, r.era_key, c.video_url, c.channel, c.published_at, r.approved_at
        FROM rankings r JOIN candidates c ON c.id = r.candidate_id
        ORDER BY COALESCE(c.published_at, r.approved_at) ASC, r.id ASC`).all(),
      db().prepare(`SELECT
        COUNT(*) AS discovered,
        COALESCE(SUM(CASE WHEN character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL THEN 1 ELSE 0 END), 0) AS classified,
        COALESCE(SUM(CASE WHEN character IS NOT NULL AND category IS NOT NULL
          AND floor IS NOT NULL AND time_ms IS NOT NULL AND time_ms > 0
          THEN 1 ELSE 0 END), 0) AS timed,
        COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS approved,
        (SELECT COUNT(*) FROM rankings) AS ranked,
        COALESCE(SUM(CASE WHEN status IN
          ('ready_for_review','time_required','classification_required')
          THEN 1 ELSE 0 END), 0) AS pending_manual,
        COALESCE(SUM(CASE WHEN COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '')
          <> '' THEN 1 ELSE 0 END), 0) AS ocr_attempted,
        COALESCE(SUM(CASE WHEN json_extract(raw_metadata, '$.ocr_outcome') = 'matched'
          THEN 1 ELSE 0 END), 0) AS ocr_matched,
        COALESCE(SUM(CASE WHEN json_extract(raw_metadata, '$.ocr_outcome')
          IN ('no_consensus','error') THEN 1 ELSE 0 END), 0) AS ocr_unresolved,
        COALESCE(SUM(CASE WHEN time_ms IS NOT NULL
          AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '') <> 'matched'
          AND confidence >= 0.95 THEN 1 ELSE 0 END), 0) AS title_times,
        COALESCE(SUM(CASE WHEN time_ms IS NOT NULL
          AND COALESCE(json_extract(raw_metadata, '$.ocr_outcome'), '') <> 'matched'
          AND confidence < 0.95 THEN 1 ELSE 0 END), 0) AS human_times,
        MAX(updated_at) AS last_updated
        FROM candidates`).first(),
    ]);
    return Response.json({
      candidates: queue.results,
      rankings: rankings.results,
      history: history.results,
      processing,
    });
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
    const playerNick = canonicalizePlayerNick(item.player_nick ?? item.channel) ?? null;
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
        playerNick, item.published_at ?? null,
        item.character ?? null, item.category ?? null, item.floor ?? null,
        item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
        item.era_key ?? "current", rawMetadata).run();
    if ((result.meta.changes ?? 0) > 0) {
      inserted += 1;
    } else {
      const update = await db().prepare(`UPDATE candidates SET
          video_url = ?, title = ?, channel = COALESCE(?, channel),
          player_nick = COALESCE(?, player_nick), published_at = COALESCE(?, published_at),
          character = ?, category = ?, floor = ?, time_ms = ?, confidence = ?, status = ?, raw_metadata = ?,
          updated_at = CURRENT_TIMESTAMP
        WHERE video_id = ?
          AND status IN ('ready_for_review','time_required','classification_required')`)
        .bind(item.video_url, item.title, item.channel ?? null,
          playerNick, item.published_at ?? null,
          item.character ?? null, item.category ?? null, item.floor ?? null,
          item.time_ms ?? null, item.confidence ?? 0, effectiveStatus,
          rawMetadata, item.video_id).run();
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
